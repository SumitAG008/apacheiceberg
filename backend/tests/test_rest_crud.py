"""
REST CRUD regression tests, targeting the actual surviving API surface.

This file originally tested a parallel /v1/tables, /v1/jobs, /v1/access-policies
API that duplicated existing functionality and was removed as dead, unwired
code (confirmed via a frontend audit -- nothing called it). Rewritten here to
cover the same behaviors against the endpoints that are actually live:
  - /v1/catalog/namespaces/{namespace}/tables            (was /v1/tables)
  - /v1/catalog/namespaces/{namespace}/tables/{table}     (was /v1/tables/{ns}/{tbl})
  - /v1/query/submit                                      (was /v1/jobs)
  - /v1/rbac/policies + /v1/rbac/user-role                (was /v1/access-policies*)
"""
import sys
import os
import pytest
from fastapi.testclient import TestClient

# Add parent directory to path so api.main can be imported
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.main import app
from auth_db import _get_conn

client = TestClient(app)
captured_otps = {}

@pytest.fixture(scope="module", autouse=True)
def mock_otp_delivery(monkeypatch_module):
    def mock_send(to_email: str, code: str, purpose: str = "login"):
        captured_otps[to_email] = {"code": code, "purpose": purpose}
        return True
    monkeypatch_module.setattr("api.main.send_email_otp", mock_send)
    yield

@pytest.fixture(scope="module")
def monkeypatch_module():
    from _pytest.monkeypatch import MonkeyPatch
    mp = MonkeyPatch()
    yield mp
    mp.undo()

@pytest.fixture(scope="module", autouse=True)
def seeded_test_table():
    """
    Ensure default.transactions_10k exists before any test runs. The app's
    own startup-event seeding (seed_demo_data) isn't guaranteed to fire
    under a bare TestClient() (no lifespan context manager), so this test
    module seeds its own minimal table directly rather than depending on
    that side effect.
    """
    from catalog_setup import get_catalog, create_namespace_if_not_exists
    from pyiceberg.schema import Schema
    from pyiceberg.types import NestedField, LongType, StringType, DoubleType
    import pyarrow as pa

    catalog = get_catalog()
    create_namespace_if_not_exists(catalog, "default")

    identifier = ("default", "transactions_10k")
    try:
        catalog.load_table(identifier)
    except Exception:
        schema = Schema(
            # LongType (int64) to match what pandas/pyarrow infers by default
            # for a plain Python int list -- IntegerType (int32) would mismatch
            # and fail the append, same issue documented in tools.py. Optional
            # (not required) so other test modules that also touch this
            # shared local-catalog table via a nullable-by-default pyarrow
            # schema don't hit a required-vs-optional compatibility error.
            NestedField(field_id=1, name="tx_id", field_type=LongType(), required=False),
            NestedField(field_id=2, name="account_from", field_type=StringType(), required=False),
            NestedField(field_id=3, name="account_to", field_type=StringType(), required=False),
            NestedField(field_id=4, name="amount", field_type=DoubleType(), required=False),
            NestedField(field_id=5, name="status", field_type=StringType(), required=False),
        )
        table = catalog.create_table(identifier, schema=schema)
        table.append(pa.Table.from_pydict({
            "tx_id": [1, 2, 3],
            "account_from": ["ACC-100", "ACC-101", "ACC-102"],
            "account_to": ["ACC-200", "ACC-201", "ACC-202"],
            "amount": [100.0, 200.0, 300.0],
            "status": ["COMPLETED", "PENDING", "COMPLETED"],
        }))
    yield


@pytest.fixture(scope="module")
def test_users():
    # Ensure auth schema and tables are fully initialized first
    from auth_db import init_auth_schema
    init_auth_schema()

    # Clear users to guarantee state
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM auth.users;")
    cur.execute("DELETE FROM auth.rbac_policies;")
    conn.commit()
    conn.close()

    admin_email = "crud_admin@example.com"
    analyst_email = "crud_analyst@example.com"
    pwd = "Password123!"

    # Create admin. NOTE: registration no longer honors a client-supplied
    # "role" field (fixed as a privilege-escalation bug) -- this becomes
    # Admin because it's the first user created after the wipe above, not
    # because of the role field. Kept in the payload for readability only.
    res = client.post("/auth/register", json={"email": admin_email, "password": pwd, "role": "Admin"})
    assert res.status_code == 200
    admin_temp = res.json()["temp_token"]
    admin_otp = captured_otps[admin_email]["code"]
    res = client.post("/auth/verify-mfa", json={"temp_token": admin_temp, "code": admin_otp})
    assert res.status_code == 200
    admin_token = res.json()["access_token"]
    assert res.json()["user"]["role"] == "Admin"

    # Create analyst -- defaults to Business Analyst regardless of payload.
    res = client.post("/auth/register", json={"email": analyst_email, "password": pwd})
    assert res.status_code == 200
    analyst_temp = res.json()["temp_token"]
    analyst_otp = captured_otps[analyst_email]["code"]
    res = client.post("/auth/verify-mfa", json={"temp_token": analyst_temp, "code": analyst_otp})
    assert res.status_code == 200
    analyst_token = res.json()["access_token"]
    assert res.json()["user"]["role"] == "Business Analyst"

    yield {
        "admin_token": admin_token,
        "analyst_token": analyst_token,
        "admin_email": admin_email,
        "analyst_email": analyst_email
    }


def test_registration_ignores_client_supplied_admin_role(test_users):
    """Regression test for the self-registration privilege-escalation fix:
    a non-first user requesting role=Admin at signup must NOT get it."""
    headers = {"Authorization": f"Bearer {test_users['admin_token']}"}
    res = client.get("/auth/me", headers=headers)
    assert res.status_code == 200
    # The analyst account, despite requesting no role / any role in its
    # payload, must be Business Analyst -- proven via a fresh registration.
    res = client.post("/auth/register", json={"email": "crud_escalation_probe@example.com", "password": "Password123!", "role": "Admin"})
    assert res.status_code == 200
    temp = res.json()["temp_token"]
    otp = captured_otps["crud_escalation_probe@example.com"]["code"]
    res = client.post("/auth/verify-mfa", json={"temp_token": temp, "code": otp})
    assert res.status_code == 200
    assert res.json()["user"]["role"] == "Business Analyst", "role=Admin in the register payload must be ignored for non-first users"


def test_list_tables(test_users):
    headers = {"Authorization": f"Bearer {test_users['admin_token']}"}
    res = client.get("/v1/catalog/namespaces/default/tables", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert "tables" in body
    assert isinstance(body["tables"], list)
    assert "transactions_10k" in body["tables"]


def test_get_table_details(test_users):
    headers = {"Authorization": f"Bearer {test_users['admin_token']}"}
    res = client.get("/v1/catalog/namespaces/default/tables/transactions_10k", headers=headers)
    assert res.status_code == 200
    details = res.json()
    assert details["namespace"] == "default"
    assert details["table_name"] == "transactions_10k"
    assert "schema" in details
    assert "history" in details

    col_names = [field["name"] for field in details["schema"]]
    assert "tx_id" in col_names
    assert "amount" in col_names


def test_submit_sql_query_job(test_users):
    headers = {"Authorization": f"Bearer {test_users['admin_token']}"}
    job_payload = {
        "mode": "sql",
        "namespace": "default",
        "table_name": "transactions_10k",
        "sql": "SELECT COUNT(*) as count FROM iceberg_table",
        "limit": 10
    }

    res = client.post("/v1/query/submit", json=job_payload, headers=headers)
    assert res.status_code == 200
    job_data = res.json()
    assert "job_id" in job_data
    # /v1/query/submit blocks until completion (submit_and_wait), unlike the
    # old /v1/jobs which returned status=running immediately and required
    # polling -- so the final status is available synchronously here.
    assert job_data["status"] == "success", job_data.get("error")
    assert job_data["result"] is not None
    assert "rows" in job_data["result"]
    assert len(job_data["result"]["rows"]) > 0


def test_python_mode_requires_elevated_role(test_users):
    """Regression test: mode=python must be blocked for Business Analyst."""
    headers = {"Authorization": f"Bearer {test_users['analyst_token']}"}
    job_payload = {
        "mode": "python",
        "namespace": "default",
        "table_name": "transactions_10k",
        "python_script": "result_df = df",
    }
    res = client.post("/v1/query/submit", json=job_payload, headers=headers)
    assert res.status_code == 403


def test_rbac_policies_admin_only(test_users):
    admin_headers = {"Authorization": f"Bearer {test_users['admin_token']}"}
    analyst_headers = {"Authorization": f"Bearer {test_users['analyst_token']}"}

    # Admin can list policies
    res = client.get("/v1/rbac/policies", headers=admin_headers)
    assert res.status_code == 200
    policies = res.json()
    assert isinstance(policies, list)

    # Analyst cannot list policies
    res = client.get("/v1/rbac/policies", headers=analyst_headers)
    assert res.status_code == 403


def test_rbac_user_role_assignment(test_users):
    admin_headers = {"Authorization": f"Bearer {test_users['admin_token']}"}
    analyst_headers = {"Authorization": f"Bearer {test_users['analyst_token']}"}

    # Admin can assign/update roles
    res = client.post(
        "/v1/rbac/user-role",
        json={"email": test_users["analyst_email"], "role": "Data Engineer"},
        headers=admin_headers,
    )
    assert res.status_code == 200
    assert "updated" in res.json()["message"].lower()

    # Analyst cannot assign/update roles
    res = client.post(
        "/v1/rbac/user-role",
        json={"email": test_users["admin_email"], "role": "Business Analyst"},
        headers=analyst_headers,
    )
    assert res.status_code == 403

    # Restore the analyst's role so later tests in this module aren't affected
    res = client.post(
        "/v1/rbac/user-role",
        json={"email": test_users["analyst_email"], "role": "Business Analyst"},
        headers=admin_headers,
    )
    assert res.status_code == 200
