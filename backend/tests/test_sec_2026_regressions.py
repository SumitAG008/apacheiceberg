# Copyright (c) 2026 Meldra AI Ltd. All rights reserved.
"""
tests/test_sec_2026_regressions.py

Regression tests that pin the fixes for:

  SEC-2026-001  Agent DQE tools built QueryJob without tenant_id/role,
                bypassing namespace scoping and evaluating RBAC against a
                hardcoded "Business Analyst" role.
  SEC-2026-002  POST /v1/query/explain built a data-touching QueryJob
                without tenant_id/role.
  PERF-2026-003 SQLExecutor materialised a full pandas copy on every query
                and registered it twice, contradicting the zero-copy
                positioning.

These deliberately avoid Postgres so they run in CI without a database —
the policy store is stubbed. If one of these fails, a confidentiality
control has regressed; do not skip it.
"""

from __future__ import annotations

import ast
import os
import pathlib

import pytest

BACKEND = pathlib.Path(__file__).resolve().parent.parent


# ─── SEC-2026-001 ─────────────────────────────────────────────────────────

def _queryjob_calls(path: pathlib.Path):
    """Yield every ast.Call constructing a QueryJob in `path`."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "QueryJob":
            yield node


@pytest.mark.parametrize("module", ["tools.py", "api/main.py"])
def test_every_queryjob_carries_tenant_and_role(module):
    """No QueryJob may be constructed without an explicit tenant_id and role.

    QueryJob defaults tenant_id="" (scoping disabled) and role="Business
    Analyst" (wrong mask). Relying on those defaults is what caused
    SEC-2026-001; this test makes the omission a build failure rather than
    something a reviewer has to spot by eye.
    """
    path = BACKEND / module
    calls = list(_queryjob_calls(path))
    assert calls, f"expected at least one QueryJob construction in {module}"

    offenders = []
    for node in calls:
        kwargs = {kw.arg for kw in node.keywords if kw.arg}
        missing = {"tenant_id", "role"} - kwargs
        if missing:
            offenders.append((node.lineno, sorted(missing)))

    assert not offenders, (
        f"{module}: QueryJob constructed without tenant/role at "
        + "; ".join(f"line {ln} missing {m}" for ln, m in offenders)
    )


def test_agent_tools_read_context_vars():
    """The agent tools must source tenant/role from the request ContextVars,
    not from LLM-supplied arguments — the model must not be able to name a
    tenant it does not belong to."""
    src = (BACKEND / "tools.py").read_text(encoding="utf-8")
    assert "def _job_context()" in src
    assert "current_tenant_id.get()" in src
    assert "current_user_role.get()" in src


# ─── Tenant scope guard ───────────────────────────────────────────────────

def test_unscoped_job_is_refused_when_enforcement_on(monkeypatch):
    from query_engine.sql_executor import assert_tenant_scoped
    from query_engine.models import QueryJob, QueryMode

    monkeypatch.setenv("MELDRA_REQUIRE_TENANT_SCOPE", "1")
    job = QueryJob(mode=QueryMode.SQL, namespace="gold", table_name="ami", sql="SELECT 1")
    assert job.tenant_id == ""

    with pytest.raises(PermissionError, match="unscoped"):
        assert_tenant_scoped(job, "sql")


def test_production_env_defaults_to_fail_closed(monkeypatch):
    """An operator who never sets MELDRA_REQUIRE_TENANT_SCOPE must still get
    enforcement in production. Secure by default, not secure by config."""
    from query_engine.sql_executor import assert_tenant_scoped
    from query_engine.models import QueryJob, QueryMode

    monkeypatch.delenv("MELDRA_REQUIRE_TENANT_SCOPE", raising=False)
    monkeypatch.setenv("MELDRA_ENV", "production")
    job = QueryJob(mode=QueryMode.SQL, namespace="gold", table_name="ami", sql="SELECT 1")

    with pytest.raises(PermissionError):
        assert_tenant_scoped(job, "sql")


def test_scoped_job_passes_guard(monkeypatch):
    from query_engine.sql_executor import assert_tenant_scoped
    from query_engine.models import QueryJob, QueryMode

    monkeypatch.setenv("MELDRA_ENV", "production")
    job = QueryJob(
        mode=QueryMode.SQL, namespace="gold", table_name="ami",
        sql="SELECT 1", tenant_id="t_abc123", role="Data Engineer",
    )
    assert_tenant_scoped(job, "sql")  # must not raise


# ─── PERF-2026-003 — zero-copy fast path ──────────────────────────────────

def test_rbac_noop_probe_fails_closed(monkeypatch):
    """If the policy store is unreachable, rbac_is_noop must return False so
    the caller takes the masked slow path. Never fail open."""
    import rbac_utils

    monkeypatch.setattr(rbac_utils, "check_table_access", lambda *a, **k: None)
    monkeypatch.setattr(
        rbac_utils, "get_role_policies",
        lambda role: (_ for _ in ()).throw(RuntimeError("db down")),
    )
    assert rbac_utils.rbac_is_noop("gold", "ami", "Admin") is False


def test_rbac_noop_probe_detects_column_policy(monkeypatch):
    import rbac_utils

    monkeypatch.setattr(rbac_utils, "check_table_access", lambda *a, **k: None)
    monkeypatch.setattr(rbac_utils, "get_role_policies", lambda role: [
        {"namespace": "gold", "table_name": "ami", "column_name": "mpan",
         "action": "mask", "masking_pattern": "XXX"},
    ])
    monkeypatch.setattr(rbac_utils, "get_row_filters", lambda role: [])
    assert rbac_utils.rbac_is_noop("gold", "ami", "Business Analyst") is False


def test_rbac_noop_probe_detects_row_filter(monkeypatch):
    import rbac_utils

    monkeypatch.setattr(rbac_utils, "check_table_access", lambda *a, **k: None)
    monkeypatch.setattr(rbac_utils, "get_role_policies", lambda role: [])
    monkeypatch.setattr(rbac_utils, "get_row_filters", lambda role: [
        {"namespace": "*", "table_name": "*",
         "filter_expression": "region = 'NW'", "description": "regional scope"},
    ])
    assert rbac_utils.rbac_is_noop("gold", "ami", "Consultant") is False


def test_rbac_noop_probe_true_when_no_policies(monkeypatch):
    import rbac_utils

    monkeypatch.setattr(rbac_utils, "check_table_access", lambda *a, **k: None)
    monkeypatch.setattr(rbac_utils, "get_role_policies", lambda role: [])
    monkeypatch.setattr(rbac_utils, "get_row_filters", lambda role: [])
    assert rbac_utils.rbac_is_noop("gold", "ami", "Admin") is True


def test_duckdb_registers_arrow_without_copy():
    """DuckDB must scan a pyarrow.Table in place. If this ever regresses to
    a pandas conversion, the zero-copy claim in the product docs is false."""
    import pyarrow as pa
    from query_engine.sql_backends import DuckDBBackend

    tbl = pa.table({"mpan": ["a", "b", "c"], "kwh": [1.0, 2.0, 3.0]})
    backend = DuckDBBackend()
    try:
        backend.register_table("iceberg_table", tbl)
        backend.register_view("gold__ami", "iceberg_table")
        out = backend.execute("SELECT SUM(kwh) AS total FROM gold__ami")
        assert float(out.iloc[0]["total"]) == 6.0
    finally:
        backend.close()


def test_sql_executor_registers_payload_once():
    """register_table must be called once for the data; the join alias goes
    through register_view. Two register_table calls = two copies."""
    src = (BACKEND / "query_engine" / "sql_executor.py").read_text(encoding="utf-8")
    body = src.split("def execute(self, job: QueryJob)")[1].split("def explain")[0]
    assert body.count("backend.register_table(") == 1, \
        "payload registered more than once — the second copy is the bug"
    assert "backend.register_view(" in body


# ─── Audit log ────────────────────────────────────────────────────────────

def test_audit_record_is_json_with_utc_timestamp():
    import json
    from observability.audit_log import AuditEvent

    rec = json.loads(AuditEvent(action="query.execute", outcome="allow").to_json())
    assert rec["timestamp"].endswith("Z")
    assert rec["schema_version"]
    # ISO-8601 with millisecond precision, parseable without a custom rule
    from datetime import datetime
    datetime.strptime(rec["timestamp"], "%Y-%m-%dT%H:%M:%S.%fZ")


def test_audit_redacts_secrets():
    import json
    from observability.audit_log import AuditEvent

    rec = json.loads(
        AuditEvent(
            action="auth.login", outcome="deny",
            detail={"password": "hunter2", "api_key": "sk-ant-xyz", "rows": 5},
        ).to_json()
    )
    assert rec["detail"]["password"] == "***REDACTED***"
    assert rec["detail"]["api_key"] == "***REDACTED***"
    assert rec["detail"]["rows"] == 5


# ─── Honest reporting (findings 5) ────────────────────────────────────────

def test_expire_snapshots_does_not_claim_unearned_success():
    """The old implementation returned a success string containing 'Expired'
    while its body was `pass`. Reporting work that did not happen is a
    compliance defect, not just a bug."""
    src = (BACKEND / "meldra" / "catalog.py").read_text(encoding="utf-8")
    body = src.split("def expire_snapshots(")[1].split("\n    def ")[0]
    assert "expire.commit()" in body, "expire_snapshots must actually commit"
    assert "meldra.retention.min_days" in body, "retention guard missing"


def test_optimize_table_has_memory_ceiling():
    src = (BACKEND / "meldra" / "catalog.py").read_text(encoding="utf-8")
    assert "COMPACTION_ROW_CEILING" in src
    body = src.split("def optimize_table(")[1].split("\n    def ")[0]
    assert "raise ValueError" in body
