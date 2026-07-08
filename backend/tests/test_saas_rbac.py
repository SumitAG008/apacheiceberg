import sys
import os
import uuid
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

@pytest.fixture(scope="module")
def test_users():
    # Ensure auth schema and tables are fully initialized first
    from auth_db import init_auth_schema
    init_auth_schema()

    # Setup - clear all existing users to ensure test user 1 is first (Admin)
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM auth.users;")
    cur.execute("DELETE FROM auth.rbac_policies;")
    conn.commit()
    conn.close()

    admin_email = "admin_test@example.com"
    analyst_email = "analyst_test@example.com"
    pwd = "Password123!"

    # Create admin first via endpoint
    res = client.post("/auth/register", json={"email": admin_email, "password": pwd, "role": "Admin"})
    assert res.status_code == 200
    admin_temp = res.json()["temp_token"]
    admin_otp = captured_otps[admin_email]["code"]
    res = client.post("/auth/verify-mfa", json={"temp_token": admin_temp, "code": admin_otp})
    assert res.status_code == 200
    admin_token = res.json()["access_token"]

    # Create analyst next via endpoint
    res = client.post("/auth/register", json={"email": analyst_email, "password": pwd, "role": "Business Analyst"})
    assert res.status_code == 200
    analyst_temp = res.json()["temp_token"]
    analyst_otp = captured_otps[analyst_email]["code"]
    res = client.post("/auth/verify-mfa", json={"temp_token": analyst_temp, "code": analyst_otp})
    assert res.status_code == 200
    analyst_token = res.json()["access_token"]

    yield {
        "admin_token": admin_token,
        "analyst_token": analyst_token,
        "admin_email": admin_email,
        "analyst_email": analyst_email
    }

def test_admin_policy_saving(test_users):
    headers = {"Authorization": f"Bearer {test_users['admin_token']}"}
    
    # Save a policy
    policy_data = {
        "policies": [
            {
                "role": "Business Analyst",
                "namespace": "default",
                "table_name": "test_table",
                "column_name": "secret_val",
                "action": "mask",
                "masking_pattern": "CONFIDENTIAL"
            }
        ]
    }
    res = client.post("/v1/rbac/policies", json=policy_data, headers=headers)
    assert res.status_code == 200
    
    # Read policies
    res = client.get("/v1/rbac/policies", headers=headers)
    assert res.status_code == 200
    policies = res.json()
    assert len(policies) > 0
    assert policies[0]["column_name"] == "secret_val"

def test_analyst_unauthorized_policy_saving(test_users):
    headers = {"Authorization": f"Bearer {test_users['analyst_token']}"}
    policy_data = {"policies": []}
    res = client.post("/v1/rbac/policies", json=policy_data, headers=headers)
    assert res.status_code == 403

def test_destructive_action_restriction(test_users):
    headers = {"Authorization": f"Bearer {test_users['analyst_token']}"}
    res = client.delete("/v1/catalog/namespaces/test_ns", headers=headers)
    assert res.status_code == 403
    assert "Access Denied" in res.json()["error"]

def test_python_workspace_sandbox(test_users):
    headers = {"Authorization": f"Bearer {test_users['admin_token']}"}
    script = "print('Hello from sandbox!')"
    res = client.post("/v1/studio/execute-python", json={"script": script}, headers=headers)
    assert res.status_code == 200
    assert "Hello from sandbox!" in res.json()["stdout"]

def test_python_workspace_analyst_denied(test_users):
    headers = {"Authorization": f"Bearer {test_users['analyst_token']}"}
    res = client.post("/v1/studio/execute-python", json={"script": "print(1)"}, headers=headers)
    assert res.status_code == 403
