# Copyright (c) 2025 Meldra AI Ltd. All rights reserved.
"""
tests/test_dqe_regression.py — DQE-specific regression tests.

Verifies that:
1. All original tools remain importable and functional post-DQE.
2. New DQE tools are importable alongside existing ones.
3. DQE tool output format is compatible with LangChain agent string expectations.
4. DQE modules import correctly without shadowing existing symbols.
5. Existing /health, /v1/graph/cypher, /v1/audit endpoints are unchanged.

Run:
    cd backend
    python -m pytest tests/test_dqe_regression.py -v
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from unittest.mock import MagicMock, patch

import networkx as nx
import pandas as pd
import pyarrow as pa
import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)


# ─────────────────────────────────────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def small_arrow_table() -> pa.Table:
    return pa.table({
        "id":     pa.array([1, 2, 3]),
        "name":   pa.array(["Alice", "Bob", "Charlie"]),
        "dept":   pa.array(["Engineering", "Engineering", "Marketing"]),
        "salary": pa.array([90000.0, 85000.0, 70000.0]),
    })


@pytest.fixture()
def simple_graph() -> nx.DiGraph:
    G = nx.DiGraph()
    G.add_node("A", label="Entity")
    G.add_node("B", label="Entity")
    G.add_edge("A", "B", label="RELATED_TO")
    return G


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION — Original tools importable and callable
# ─────────────────────────────────────────────────────────────────────────────

class TestOriginalToolsUnchanged:

    def test_all_original_tools_importable(self):
        from tools import (
            create_iceberg_table,
            ingest_csv_to_iceberg,
            query_iceberg_data,
            run_generic_graph_analysis,
            sync_iceberg_to_graph_db,
            query_graph_db_cypher,
        )
        for tool in [create_iceberg_table, ingest_csv_to_iceberg, query_iceberg_data,
                     run_generic_graph_analysis, sync_iceberg_to_graph_db, query_graph_db_cypher]:
            assert callable(tool.func), f"{tool.name} is not callable"

    def test_query_iceberg_data_handles_missing_table(self):
        from tools import query_iceberg_data
        with patch("tools.get_catalog") as mock_cat:
            mock_cat.return_value.load_table.side_effect = Exception("Not found")
            result = query_iceberg_data.invoke({
                "namespace": "bad", "table_name": "bad", "sql_query": "SELECT 1"
            })
        assert "Error" in result

    def test_query_iceberg_data_runs_sql(self, small_arrow_table):
        from tools import query_iceberg_data
        with patch("tools.get_catalog") as mock_cat:
            mock_tbl = MagicMock()
            mock_tbl.scan.return_value.to_arrow.return_value = small_arrow_table
            mock_cat.return_value.load_table.return_value = mock_tbl
            result = query_iceberg_data.invoke({
                "namespace": "default",
                "table_name": "employees_sample",
                "sql_query": "SELECT COUNT(*) as cnt FROM iceberg_table"
            })
        assert "3" in result

    def test_cypher_tool_empty_result(self):
        from tools import query_graph_db_cypher
        with patch("tools.execute_cypher_query") as mock_qry:
            mock_qry.return_value = pd.DataFrame()
            result = query_graph_db_cypher.invoke({"graph_name": "g", "cypher_query": "MATCH (n) RETURN n"})
        assert "0 results" in result

    def test_cypher_tool_error_handling(self):
        from tools import query_graph_db_cypher
        with patch("tools.execute_cypher_query") as mock_qry:
            mock_qry.side_effect = Exception("DB down")
            result = query_graph_db_cypher.invoke({"graph_name": "g", "cypher_query": "MATCH (n) RETURN n"})
        assert "Error" in result

    def test_run_generic_graph_analysis_find_cycles(self):
        from tools import run_generic_graph_analysis
        df = pd.DataFrame({"source": ["A", "B", "C"], "target": ["B", "C", "A"]})
        arrow = pa.Table.from_pandas(df)
        with patch("tools.get_catalog") as mock_cat:
            mock_tbl = MagicMock()
            mock_tbl.scan.return_value.to_arrow.return_value = arrow
            mock_cat.return_value.load_table.return_value = mock_tbl
            result = run_generic_graph_analysis.invoke({
                "namespace": "default", "table_name": "t",
                "source_node_col": "source", "target_node_col": "target",
                "algorithm": "find_cycles",
            })
        assert isinstance(result, str)


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION — DQE tools importable alongside existing tools
# ─────────────────────────────────────────────────────────────────────────────

class TestDQEToolsCoexistence:

    def test_all_dqe_tools_importable(self):
        from tools import (
            distributed_sql_query,
            distributed_graph_query,
            distributed_python_extract,
            multi_engine_query,
        )
        for tool in [distributed_sql_query, distributed_graph_query,
                     distributed_python_extract, multi_engine_query]:
            assert callable(tool.func)

    def test_dqe_package_importable(self):
        from query_engine import QueryEngine, QueryJob, QueryMode, QueryResult, QueryStatus
        assert QueryEngine
        assert QueryJob
        assert QueryMode
        assert QueryResult
        assert QueryStatus

    def test_job_store_singleton(self):
        from query_engine.job_store import job_store
        assert job_store is not None
        stats = job_store.stats()
        assert "total_jobs" in stats

    def test_executor_singleton(self):
        from query_engine.executor import query_engine
        assert query_engine is not None
        modes = query_engine.supported_modes()
        assert len(modes) == 3

    def test_no_symbol_shadowing(self):
        """Ensure DQE imports don't shadow get_catalog or other core symbols."""
        import tools as tools_module
        assert hasattr(tools_module, "get_catalog")
        assert hasattr(tools_module, "execute_cypher_query")
        assert hasattr(tools_module, "sync_dataframe_to_age")


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION — DQE tool output format (string, agent-compatible)
# ─────────────────────────────────────────────────────────────────────────────

class TestDQEToolOutputFormat:

    def test_sql_tool_success_output(self):
        from tools import distributed_sql_query
        from query_engine.sql_executor import SQLExecutor
        arrow = pa.table({"a": [1, 2], "b": ["x", "y"]})
        with patch.object(SQLExecutor, "_load_iceberg", return_value=arrow):
            result = distributed_sql_query.invoke({
                "namespace": "default", "table_name": "t",
                "sql": "SELECT a, b FROM iceberg_table", "limit": 100,
            })
        assert isinstance(result, str)
        assert "a" in result
        assert "✅" in result

    def test_sql_tool_error_output(self):
        from tools import distributed_sql_query
        from query_engine.sql_executor import SQLExecutor
        with patch.object(SQLExecutor, "_load_iceberg", side_effect=ValueError("Table not found")):
            result = distributed_sql_query.invoke({
                "namespace": "bad", "table_name": "bad",
                "sql": "SELECT 1", "limit": 10,
            })
        assert isinstance(result, str)
        assert "❌" in result

    def test_python_tool_success_output(self):
        from tools import distributed_python_extract
        from query_engine.python_executor import PythonExecutor
        arrow = pa.table({"amount": [100.0, 200.0, 300.0]})
        with patch.object(PythonExecutor, "_load_iceberg", return_value=arrow):
            result = distributed_python_extract.invoke({
                "namespace": "default", "table_name": "t",
                "python_script": "result_df = df[df['amount'] > 150]",
                "limit": 100,
            })
        assert isinstance(result, str)
        assert "amount" in result
        assert "✅" in result

    def test_python_tool_security_error_output(self):
        from tools import distributed_python_extract
        from query_engine.python_executor import PythonExecutor
        arrow = pa.table({"x": [1]})
        with patch.object(PythonExecutor, "_load_iceberg", return_value=arrow):
            result = distributed_python_extract.invoke({
                "namespace": "default", "table_name": "t",
                "python_script": "import os\nresult_df = df",
                "limit": 100,
            })
        assert isinstance(result, str)
        assert "❌" in result

    def test_multi_engine_tool_output(self):
        from tools import multi_engine_query
        from query_engine.sql_executor import SQLExecutor
        arrow = pa.table({"x": [1]})
        specs = json.dumps([{
            "mode": "sql", "namespace": "default", "table_name": "t",
            "sql": "SELECT x FROM iceberg_table",
        }])
        with patch.object(SQLExecutor, "_load_iceberg", return_value=arrow):
            result = multi_engine_query.invoke({"queries_json": specs})
        assert isinstance(result, str)

    def test_multi_engine_bad_json(self):
        from tools import multi_engine_query
        result = multi_engine_query.invoke({"queries_json": "not valid json"})
        assert isinstance(result, str)
        assert "❌" in result

    def test_multi_engine_too_many_queries(self):
        from tools import multi_engine_query
        specs = json.dumps([
            {"mode": "sql", "namespace": "default", "table_name": "t", "sql": f"SELECT {i}"}
            for i in range(11)
        ])
        result = multi_engine_query.invoke({"queries_json": specs})
        assert "Maximum 10" in result


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION — Existing FastAPI endpoints unchanged
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def _test_client_regression():
    try:
        from fastapi.testclient import TestClient
        import api.main as main_module
        main_module.app.router.on_startup.clear()
        main_module.app.router.on_shutdown.clear()
        return TestClient(main_module.app, raise_server_exceptions=False)
    except Exception as exc:
        pytest.skip(f"Could not build TestClient: {exc}")


def _make_admin_jwt() -> dict:
    try:
        from datetime import datetime, timedelta
        from jose import jwt as jose_jwt
        secret = os.environ.get("JWT_SECRET_KEY", "test-secret-key-for-testing-only-32chars")
        token = jose_jwt.encode(
            {"sub": "dqe-regression-user", "email": "dqe@meldra.ai",
             "tier": "trial", "role": "Admin", "type": "access",
             "exp": datetime.utcnow() + timedelta(minutes=30)},
            secret, algorithm="HS256",
        )
        return {"Authorization": f"Bearer {token}"}
    except Exception:
        return {}


class TestExistingEndpointsUnchanged:

    def test_health_still_works(self, _test_client_regression):
        resp = _test_client_regression.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_graph_cypher_requires_auth(self, _test_client_regression):
        resp = _test_client_regression.post(
            "/v1/graph/cypher", json={"graph_name": "g", "query": "MATCH (n) RETURN n"}
        )
        assert resp.status_code == 401

    def test_audit_requires_auth(self, _test_client_regression):
        resp = _test_client_regression.get("/v1/audit")
        assert resp.status_code == 401

    def test_auth_me_requires_auth(self, _test_client_regression):
        resp = _test_client_regression.get("/auth/me")
        assert resp.status_code == 401

    def test_dqe_modes_endpoint_registered(self, _test_client_regression):
        """DQE route must be registered — should NOT return 404."""
        resp = _test_client_regression.get("/v1/query/modes", headers=_make_admin_jwt())
        assert resp.status_code != 404

    def test_dqe_submit_endpoint_registered(self, _test_client_regression):
        resp = _test_client_regression.post(
            "/v1/query/submit",
            json={"mode": "sql"},  # will 422 but not 404
        )
        assert resp.status_code != 404

    def test_dqe_history_endpoint_registered(self, _test_client_regression):
        resp = _test_client_regression.get("/v1/query/history", headers=_make_admin_jwt())
        assert resp.status_code != 404
