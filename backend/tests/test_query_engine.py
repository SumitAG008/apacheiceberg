# Copyright (c) 2025 Meldra AI Ltd. All rights reserved.
"""
tests/test_query_engine.py — Comprehensive pytest suite for the Distributed Query Engine.

Unit tests cover all three executors (SQL, Graph, Python) plus the job store.
Integration tests cover the FastAPI REST endpoints.

Run:
    cd backend
    python -m pytest tests/test_query_engine.py -v
    python -m pytest tests/test_query_engine.py -v -k "unit"
    python -m pytest tests/test_query_engine.py -v -k "integration"
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import networkx as nx
import pandas as pd
import pyarrow as pa
import pytest

# ── Path setup ────────────────────────────────────────────────────────────────
# Ensure backend/ is on sys.path so imports resolve correctly
_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)


# ─────────────────────────────────────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def sample_arrow_table() -> pa.Table:
    """A small PyArrow table simulating an Iceberg scan result."""
    return pa.table({
        "tx_id":        pa.array([1, 2, 3, 4, 5], type=pa.int32()),
        "account_from": pa.array(["ACC-001", "ACC-002", "ACC-001", "ACC-003", "ACC-002"]),
        "account_to":   pa.array(["ACC-002", "ACC-003", "ACC-003", "ACC-001", "ACC-001"]),
        "amount":       pa.array([1000.0, 2500.0, 500.0, 9999.0, 15000.0], type=pa.float64()),
        "status":       pa.array(["COMPLETED", "COMPLETED", "PENDING", "COMPLETED", "FAILED"]),
    })


@pytest.fixture()
def sample_dataframe(sample_arrow_table) -> pd.DataFrame:
    return sample_arrow_table.to_pandas()


@pytest.fixture()
def sample_graph() -> nx.DiGraph:
    """A small DiGraph for graph executor tests."""
    G = nx.DiGraph()
    G.add_node("ACC-001", label="Account")
    G.add_node("ACC-002", label="Account")
    G.add_node("ACC-003", label="Account")
    G.add_edge("ACC-001", "ACC-002", label="SENT_TO")
    G.add_edge("ACC-002", "ACC-003", label="SENT_TO")
    G.add_edge("ACC-003", "ACC-001", label="SENT_TO")  # cycle
    return G


@pytest.fixture()
def job_store_fresh():
    """Return a fresh JobStore instance (not the singleton)."""
    from query_engine.job_store import JobStore
    return JobStore()


@pytest.fixture()
def mock_catalog(sample_arrow_table):
    """Mock PyIceberg catalog that returns sample_arrow_table on scan."""
    mock_table = MagicMock()
    mock_table.scan.return_value.to_arrow.return_value = sample_arrow_table
    mock_catalog = MagicMock()
    mock_catalog.load_table.return_value = mock_table
    return mock_catalog


# ─────────────────────────────────────────────────────────────────────────────
# UNIT TESTS — Job Store
# ─────────────────────────────────────────────────────────────────────────────

class TestJobStore:

    def test_create_and_get(self, job_store_fresh):
        from query_engine.models import QueryJob, QueryMode
        store = job_store_fresh
        job = QueryJob(mode=QueryMode.SQL, namespace="default", table_name="t", sql="SELECT 1")
        store.create(job)
        fetched = store.get(job.job_id)
        assert fetched is not None
        assert fetched.job_id == job.job_id

    def test_get_nonexistent_returns_none(self, job_store_fresh):
        result = job_store_fresh.get("non-existent-id")
        assert result is None

    def test_update_job(self, job_store_fresh):
        from query_engine.models import QueryJob, QueryMode, QueryStatus
        store = job_store_fresh
        job = QueryJob(mode=QueryMode.SQL, namespace="default", table_name="t", sql="SELECT 1")
        store.create(job)
        job.status = QueryStatus.SUCCESS
        store.update(job)
        assert store.get(job.job_id).status == QueryStatus.SUCCESS

    def test_list_for_user(self, job_store_fresh):
        from query_engine.models import QueryJob, QueryMode
        store = job_store_fresh
        for i in range(3):
            job = QueryJob(mode=QueryMode.SQL, namespace="default", table_name="t", sql=f"SELECT {i}")
            job.submitted_by = "user-1"
            store.create(job)
        # Different user job
        other_job = QueryJob(mode=QueryMode.SQL, namespace="default", table_name="t", sql="SELECT 99")
        other_job.submitted_by = "user-2"
        store.create(other_job)
        user1_jobs = store.list_for_user("user-1")
        assert len(user1_jobs) == 3
        user2_jobs = store.list_for_user("user-2")
        assert len(user2_jobs) == 1

    def test_ttl_expiry(self, job_store_fresh):
        from query_engine.models import QueryJob, QueryMode
        store = job_store_fresh
        job = QueryJob(mode=QueryMode.SQL, namespace="default", table_name="t", sql="SELECT 1")
        store.create(job)
        # Force expiry by backdating the timestamp
        store._timestamps[job.job_id] = time.time() - 7201  # > 1h TTL
        assert store.get(job.job_id) is None  # triggers _prune

    def test_stats(self, job_store_fresh):
        stats = job_store_fresh.stats()
        assert "total_jobs" in stats
        assert "by_status" in stats
        assert stats["ttl_seconds"] == 3600

    def test_delete(self, job_store_fresh):
        from query_engine.models import QueryJob, QueryMode
        store = job_store_fresh
        job = QueryJob(mode=QueryMode.SQL, namespace="default", table_name="t", sql="SELECT 1")
        store.create(job)
        assert store.delete(job.job_id) is True
        assert store.get(job.job_id) is None
        assert store.delete("non-existent") is False


# ─────────────────────────────────────────────────────────────────────────────
# UNIT TESTS — QueryJob Model Validation
# ─────────────────────────────────────────────────────────────────────────────

class TestQueryJobModel:

    def test_sql_mode_requires_sql_field(self):
        from query_engine.models import QueryJob, QueryMode
        with pytest.raises(ValueError, match="'sql' is required"):
            QueryJob(mode=QueryMode.SQL, namespace="default", table_name="t")

    def test_sql_mode_requires_namespace(self):
        from query_engine.models import QueryJob, QueryMode
        with pytest.raises(ValueError, match="'namespace'"):
            QueryJob(mode=QueryMode.SQL, sql="SELECT 1")

    def test_graph_mode_requires_graph_name(self):
        from query_engine.models import QueryJob, QueryMode
        with pytest.raises(ValueError, match="'graph_name'"):
            QueryJob(mode=QueryMode.GRAPH, cypher="MATCH (n) RETURN n")

    def test_graph_mode_requires_cypher_or_algorithm(self):
        from query_engine.models import QueryJob, QueryMode
        with pytest.raises(ValueError, match="'cypher' or 'algorithm'"):
            QueryJob(mode=QueryMode.GRAPH, graph_name="g")

    def test_python_mode_requires_script(self):
        from query_engine.models import QueryJob, QueryMode
        with pytest.raises(ValueError, match="'python_script'"):
            QueryJob(mode=QueryMode.PYTHON, namespace="default", table_name="t")

    def test_python_mode_requires_namespace(self):
        from query_engine.models import QueryJob, QueryMode
        with pytest.raises(ValueError):
            QueryJob(mode=QueryMode.PYTHON, python_script="result_df = df")

    def test_valid_sql_job_created(self):
        from query_engine.models import QueryJob, QueryMode, QueryStatus
        job = QueryJob(mode=QueryMode.SQL, namespace="ns", table_name="tbl", sql="SELECT 1")
        assert job.status == QueryStatus.PENDING
        assert job.job_id is not None
        assert job.created_at is not None

    def test_limit_constraint(self):
        from query_engine.models import QueryJob, QueryMode
        with pytest.raises(ValueError):
            QueryJob(mode=QueryMode.SQL, namespace="ns", table_name="t", sql="SELECT 1", limit=0)
        with pytest.raises(ValueError):
            QueryJob(mode=QueryMode.SQL, namespace="ns", table_name="t", sql="SELECT 1", limit=99999)


# ─────────────────────────────────────────────────────────────────────────────
# UNIT TESTS — SQL Executor
# ─────────────────────────────────────────────────────────────────────────────

class TestSQLExecutor:

    def _make_job(self, sql: str, limit: int = 1000) -> "QueryJob":
        from query_engine.models import QueryJob, QueryMode
        return QueryJob(
            mode=QueryMode.SQL, namespace="default", table_name="transactions", sql=sql, limit=limit
        )

    def _run(self, sql: str, arrow_table: pa.Table, limit: int = 1000):
        from query_engine.sql_executor import SQLExecutor
        executor = SQLExecutor()
        job = self._make_job(sql, limit)
        with patch.object(executor, "_get_catalog") as mock_cat_fn:
            mock_table = MagicMock()
            mock_table.scan.return_value.to_arrow.return_value = arrow_table
            mock_table.schema.return_value.as_arrow.return_value = arrow_table.schema
            mock_catalog = MagicMock()
            mock_catalog.load_table.return_value = mock_table
            mock_cat_fn.return_value = mock_catalog
            # Also patch the static _load_iceberg method
            with patch.object(SQLExecutor, "_load_iceberg", return_value=arrow_table):
                return executor.execute(job)

    def test_basic_select_all(self, sample_arrow_table):
        result = self._run("SELECT * FROM iceberg_table", sample_arrow_table)
        assert result.total_rows == 5
        assert "tx_id" in result.columns
        assert result.engine_used == "duckdb"

    def test_aggregation_sum(self, sample_arrow_table):
        result = self._run(
            "SELECT account_from, SUM(amount) as total FROM iceberg_table GROUP BY account_from ORDER BY total DESC",
            sample_arrow_table,
        )
        assert result.total_rows == 3  # 3 unique account_from values
        assert "total" in result.columns

    def test_count_query(self, sample_arrow_table):
        result = self._run("SELECT COUNT(*) as cnt FROM iceberg_table", sample_arrow_table)
        assert result.rows[0]["cnt"] == 5

    def test_where_filter(self, sample_arrow_table):
        result = self._run(
            "SELECT * FROM iceberg_table WHERE status = 'COMPLETED'", sample_arrow_table
        )
        assert result.total_rows == 3

    def test_order_by_limit(self, sample_arrow_table):
        result = self._run(
            "SELECT * FROM iceberg_table ORDER BY amount DESC LIMIT 2", sample_arrow_table
        )
        assert result.total_rows == 2
        assert result.rows[0]["amount"] == 15000.0

    def test_truncation(self, sample_arrow_table):
        result = self._run("SELECT * FROM iceberg_table", sample_arrow_table, limit=2)
        assert result.truncated is True
        assert len(result.rows) == 2
        assert result.total_rows == 5

    def test_no_truncation_when_within_limit(self, sample_arrow_table):
        result = self._run("SELECT * FROM iceberg_table", sample_arrow_table, limit=100)
        assert result.truncated is False

    def test_execution_plan_present(self, sample_arrow_table):
        result = self._run("SELECT * FROM iceberg_table LIMIT 1", sample_arrow_table)
        assert result.execution_plan is not None
        assert "DQE/SQL" in result.execution_plan

    def test_bad_sql_raises(self, sample_arrow_table):
        from query_engine.sql_executor import SQLExecutor
        executor = SQLExecutor()
        job = self._make_job("SELECT FROM WHERE INVALID SYNTAX!!!!")
        with patch.object(SQLExecutor, "_load_iceberg", return_value=sample_arrow_table):
            with pytest.raises(Exception):
                executor.execute(job)

    def test_explain_returns_string(self, sample_arrow_table):
        from query_engine.sql_executor import SQLExecutor
        executor = SQLExecutor()
        job = self._make_job("SELECT COUNT(*) FROM iceberg_table")
        with patch.object(SQLExecutor, "_load_iceberg", return_value=sample_arrow_table):
            with patch.object(executor, "_get_catalog"):
                plan = executor.explain(job)
        assert isinstance(plan, str)


# ─────────────────────────────────────────────────────────────────────────────
# UNIT TESTS — Graph Executor
# ─────────────────────────────────────────────────────────────────────────────

class TestGraphExecutor:

    def _run(self, job, graph: nx.DiGraph):
        from query_engine.graph_executor import GraphExecutor
        executor = GraphExecutor()
        with patch.object(GraphExecutor, "_load_graph", return_value=graph):
            return executor.execute(job)

    def _job(self, **kwargs):
        from query_engine.models import QueryJob, QueryMode
        return QueryJob(mode=QueryMode.GRAPH, graph_name="test_graph", **kwargs)

    def test_node_listing(self, sample_graph):
        job = self._job(cypher="MATCH (n) RETURN n LIMIT 10")
        result = self._run(job, sample_graph)
        assert result.total_rows == 3
        assert "node_id" in result.columns

    def test_edge_traversal(self, sample_graph):
        job = self._job(cypher="MATCH (a)-[r]->(b) RETURN a.node_id, b.node_id LIMIT 50")
        result = self._run(job, sample_graph)
        assert result.total_rows == 3
        assert "source_id" in result.columns
        assert "target_id" in result.columns

    def test_pagerank_algorithm(self, sample_graph):
        job = self._job(algorithm="pagerank")
        result = self._run(job, sample_graph)
        assert "pagerank_score" in result.columns
        assert len(result.rows) == 3

    def test_betweenness_centrality(self, sample_graph):
        job = self._job(algorithm="betweenness_centrality")
        result = self._run(job, sample_graph)
        assert "betweenness" in result.columns

    def test_degree_centrality(self, sample_graph):
        job = self._job(algorithm="degree_centrality")
        result = self._run(job, sample_graph)
        assert "degree_centrality" in result.columns

    def test_connected_components(self, sample_graph):
        job = self._job(algorithm="connected_components")
        result = self._run(job, sample_graph)
        assert "component_id" in result.columns
        # All 3 nodes are in one cycle, so 1 component
        assert result.rows[0]["size"] == 3

    def test_find_cycles(self, sample_graph):
        job = self._job(algorithm="find_cycles")
        result = self._run(job, sample_graph)
        assert "path" in result.columns
        # The graph has a 3-node cycle
        cycle_rows = [r for r in result.rows if r.get("length", 0) == 3]
        assert len(cycle_rows) >= 1

    def test_shortest_path(self, sample_graph):
        job = self._job(algorithm="shortest_path", filters={"source": "ACC-001", "target": "ACC-003"})
        result = self._run(job, sample_graph)
        assert "node_id" in result.columns
        assert result.rows[0]["node_id"] == "ACC-001"

    def test_shortest_path_no_path(self, sample_graph):
        # Add isolated node
        sample_graph.add_node("ISOLATED")
        job = self._job(algorithm="shortest_path", filters={"source": "ACC-001", "target": "ISOLATED"})
        result = self._run(job, sample_graph)
        assert "No path" in result.rows[0]["node_id"]

    def test_unsupported_algorithm_raises(self, sample_graph):
        from query_engine.graph_executor import GraphExecutor
        executor = GraphExecutor()
        job = self._job(algorithm="nonexistent_algo")
        with patch.object(GraphExecutor, "_load_graph", return_value=sample_graph):
            with pytest.raises(ValueError, match="Unknown algorithm"):
                executor.execute(job)

    def test_explain_returns_string(self, sample_graph):
        from query_engine.graph_executor import GraphExecutor
        executor = GraphExecutor()
        job = self._job(algorithm="pagerank")
        with patch.object(GraphExecutor, "_load_graph", return_value=sample_graph):
            plan = executor.explain(job)
        assert isinstance(plan, str)
        assert "pagerank" in plan.lower()


# ─────────────────────────────────────────────────────────────────────────────
# UNIT TESTS — Python Executor (AST safety + execution)
# ─────────────────────────────────────────────────────────────────────────────

class TestPythonExecutor:

    def _run(self, script: str, arrow_table: pa.Table, limit: int = 500):
        from query_engine.python_executor import PythonExecutor
        from query_engine.models import QueryJob, QueryMode
        executor = PythonExecutor()
        job = QueryJob(
            mode=QueryMode.PYTHON,
            namespace="default",
            table_name="transactions",
            python_script=script,
            limit=limit,
        )
        with patch.object(PythonExecutor, "_load_iceberg", return_value=arrow_table):
            return executor.execute(job)

    def test_basic_filter(self, sample_arrow_table):
        script = "result_df = df[df['status'] == 'COMPLETED']"
        result = self._run(script, sample_arrow_table)
        assert result.total_rows == 3
        assert result.engine_used == "python_exec"

    def test_groupby_aggregation(self, sample_arrow_table):
        script = (
            "result_df = df.groupby('account_from')['amount']"
            ".sum().reset_index(name='total_amount')"
        )
        result = self._run(script, sample_arrow_table)
        assert result.total_rows == 3
        assert "total_amount" in result.columns

    def test_column_rename(self, sample_arrow_table):
        script = "result_df = df.rename(columns={'tx_id': 'transaction_id'})"
        result = self._run(script, sample_arrow_table)
        assert "transaction_id" in result.columns

    def test_complex_multi_step(self, sample_arrow_table):
        script = """
high_value = df[df['amount'] > 1000].copy()
high_value['is_large'] = high_value['amount'] > 5000
result_df = high_value[['account_from', 'amount', 'is_large']].sort_values('amount', ascending=False)
"""
        result = self._run(script, sample_arrow_table)
        assert result.total_rows >= 1
        assert "is_large" in result.columns

    def test_missing_result_df_raises(self, sample_arrow_table):
        from query_engine.python_executor import PythonExecutor
        from query_engine.models import QueryJob, QueryMode
        executor = PythonExecutor()
        script = "x = 1 + 1"  # no result_df
        job = QueryJob(mode=QueryMode.PYTHON, namespace="default", table_name="t", python_script=script)
        with patch.object(PythonExecutor, "_load_iceberg", return_value=sample_arrow_table):
            with pytest.raises(ValueError, match="result_df"):
                executor.execute(job)

    def test_blocks_os_import(self, sample_arrow_table):
        from query_engine.python_executor import SecurityError
        script = "import os\nresult_df = df"
        with pytest.raises(SecurityError, match="os"):
            self._run(script, sample_arrow_table)

    def test_blocks_subprocess_import(self, sample_arrow_table):
        from query_engine.python_executor import SecurityError
        script = "import subprocess\nresult_df = df"
        with pytest.raises(SecurityError, match="subprocess"):
            self._run(script, sample_arrow_table)

    def test_blocks_sys_import(self, sample_arrow_table):
        from query_engine.python_executor import SecurityError
        script = "import sys\nresult_df = df"
        with pytest.raises(SecurityError, match="sys"):
            self._run(script, sample_arrow_table)

    def test_blocks_open_call(self, sample_arrow_table):
        from query_engine.python_executor import SecurityError
        script = "f = open('/etc/passwd')\nresult_df = df"
        with pytest.raises(SecurityError, match="open"):
            self._run(script, sample_arrow_table)

    def test_blocks_exec_call(self, sample_arrow_table):
        from query_engine.python_executor import SecurityError
        script = "exec('x=1')\nresult_df = df"
        with pytest.raises(SecurityError, match="exec"):
            self._run(script, sample_arrow_table)

    def test_blocks_eval_call(self, sample_arrow_table):
        from query_engine.python_executor import SecurityError
        script = "eval('1+1')\nresult_df = df"
        with pytest.raises(SecurityError, match="eval"):
            self._run(script, sample_arrow_table)

    def test_blocks_dunder_access(self, sample_arrow_table):
        from query_engine.python_executor import SecurityError
        script = "x = ().__class__.__bases__[0].__subclasses__()\nresult_df = df"
        with pytest.raises(SecurityError):
            self._run(script, sample_arrow_table)

    def test_syntax_error_raises(self, sample_arrow_table):
        script = "result_df = df[[[["  # syntax error
        with pytest.raises(ValueError, match="Syntax error"):
            self._run(script, sample_arrow_table)

    def test_timeout_enforced(self, sample_arrow_table):
        """Verify that an infinite loop is terminated within the timeout."""
        from query_engine.python_executor import PythonExecutor, EXECUTION_TIMEOUT_SECONDS
        if EXECUTION_TIMEOUT_SECONDS > 5:
            pytest.skip("Timeout too long for CI; set EXECUTION_TIMEOUT_SECONDS <= 5 to run")
        script = "import time as _t\nwhile True: _t.sleep(0.1)"
        with pytest.raises((TimeoutError, Exception)):
            self._run(script, sample_arrow_table)

    def test_result_df_not_dataframe_raises(self, sample_arrow_table):
        script = "result_df = [1, 2, 3]"  # not a DataFrame
        with pytest.raises(ValueError, match="pandas DataFrame"):
            self._run(script, sample_arrow_table)

    def test_truncation(self, sample_arrow_table):
        script = "result_df = df"
        result = self._run(script, sample_arrow_table, limit=2)
        assert result.truncated is True
        assert len(result.rows) == 2

    def test_explain_validates_ast(self, sample_arrow_table):
        from query_engine.python_executor import PythonExecutor
        from query_engine.models import QueryJob, QueryMode
        executor = PythonExecutor()
        job = QueryJob(
            mode=QueryMode.PYTHON, namespace="default", table_name="t",
            python_script="result_df = df.head(10)"
        )
        plan = executor.explain(job)
        assert "DQE/PYTHON" in plan


# ─────────────────────────────────────────────────────────────────────────────
# UNIT TESTS — QueryEngine router (submit_sync)
# ─────────────────────────────────────────────────────────────────────────────

class TestQueryEngineRouter:

    def test_submit_sync_sql(self, sample_arrow_table):
        from query_engine.executor import QueryEngine
        from query_engine.models import QueryJob, QueryMode, QueryStatus
        from query_engine.sql_executor import SQLExecutor

        engine = QueryEngine()
        job = QueryJob(
            mode=QueryMode.SQL, namespace="default", table_name="t",
            sql="SELECT COUNT(*) as cnt FROM iceberg_table"
        )
        with patch.object(SQLExecutor, "_load_iceberg", return_value=sample_arrow_table):
            completed = engine.submit_sync(job)

        assert completed.status == QueryStatus.SUCCESS
        assert completed.result is not None
        assert completed.result.engine_used == "duckdb"

    def test_submit_sync_python(self, sample_arrow_table):
        from query_engine.executor import QueryEngine
        from query_engine.models import QueryJob, QueryMode, QueryStatus
        from query_engine.python_executor import PythonExecutor

        engine = QueryEngine()
        job = QueryJob(
            mode=QueryMode.PYTHON, namespace="default", table_name="t",
            python_script="result_df = df.head(2)"
        )
        with patch.object(PythonExecutor, "_load_iceberg", return_value=sample_arrow_table):
            completed = engine.submit_sync(job)

        assert completed.status == QueryStatus.SUCCESS
        assert completed.result.total_rows == 2

    def test_submit_sync_failed_job_has_error(self, sample_arrow_table):
        from query_engine.executor import QueryEngine
        from query_engine.models import QueryJob, QueryMode, QueryStatus
        from query_engine.sql_executor import SQLExecutor

        engine = QueryEngine()
        job = QueryJob(
            mode=QueryMode.SQL, namespace="default", table_name="t",
            sql="SELECT * FROM nonexistent_view"  # will fail — table not registered
        )
        with patch.object(SQLExecutor, "_load_iceberg", return_value=sample_arrow_table):
            completed = engine.submit_sync(job)

        assert completed.status == QueryStatus.FAILED
        assert completed.error is not None

    def test_explain_sql(self, sample_arrow_table):
        from query_engine.executor import QueryEngine
        from query_engine.models import QueryJob, QueryMode
        from query_engine.sql_executor import SQLExecutor

        engine = QueryEngine()
        job = QueryJob(mode=QueryMode.SQL, namespace="ns", table_name="t", sql="SELECT 1")
        with patch.object(SQLExecutor, "_load_iceberg", return_value=sample_arrow_table):
            plan = engine.explain(job)
        assert isinstance(plan, str)

    def test_supported_modes_returns_three(self):
        from query_engine.executor import QueryEngine
        engine = QueryEngine()
        modes = engine.supported_modes()
        assert len(modes) == 3
        mode_names = {m["mode"] for m in modes}
        assert mode_names == {"sql", "graph", "python"}


# ─────────────────────────────────────────────────────────────────────────────
# INTEGRATION TESTS — FastAPI REST endpoints
# These require a running app; use TestClient with mocked Iceberg catalog.
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def test_client():
    """Create a FastAPI TestClient with mocked Iceberg + auth."""
    try:
        from fastapi.testclient import TestClient
        import api.main as main_module

        # Stub out startup events that need DB / Iceberg
        main_module.app.router.on_startup.clear()
        main_module.app.router.on_shutdown.clear()

        client = TestClient(main_module.app, raise_server_exceptions=False)
        return client
    except Exception as exc:
        pytest.skip(f"Could not create TestClient: {exc}")


def _auth_headers() -> Dict[str, str]:
    """Generate a valid JWT for integration tests."""
    try:
        import os
        from datetime import datetime, timedelta, timezone
        from jose import jwt as jose_jwt
        secret = os.environ.get("JWT_SECRET_KEY", "test-secret-key-for-testing-only-32chars")
        token = jose_jwt.encode(
            {
                "sub": "test-user-id",
                "email": "test@meldra.ai",
                "tier": "trial",
                "role": "Admin",
                "type": "access",
                "exp": datetime.now(timezone.utc) + timedelta(minutes=30),
            },
            secret,
            algorithm="HS256",
        )
        return {"Authorization": f"Bearer {token}"}
    except Exception:
        return {}


class TestDQEEndpoints:

    def test_get_modes_requires_auth(self, test_client):
        resp = test_client.get("/v1/query/modes")
        assert resp.status_code == 401

    def test_get_modes_authenticated(self, test_client, sample_arrow_table):
        from query_engine.sql_executor import SQLExecutor
        with patch.object(SQLExecutor, "_load_iceberg", return_value=sample_arrow_table):
            resp = test_client.get("/v1/query/modes", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "modes" in data
        assert len(data["modes"]) == 3

    def test_submit_sql_query(self, test_client, sample_arrow_table):
        from query_engine.sql_executor import SQLExecutor
        with patch.object(SQLExecutor, "_load_iceberg", return_value=sample_arrow_table):
            resp = test_client.post(
                "/v1/query/submit",
                json={
                    "mode": "sql",
                    "namespace": "default",
                    "table_name": "transactions_10k",
                    "sql": "SELECT COUNT(*) as cnt FROM iceberg_table",
                    "limit": 100,
                },
                headers=_auth_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["result"]["rows"][0]["cnt"] == 5

    def test_submit_python_query(self, test_client, sample_arrow_table):
        from query_engine.python_executor import PythonExecutor
        with patch.object(PythonExecutor, "_load_iceberg", return_value=sample_arrow_table):
            resp = test_client.post(
                "/v1/query/submit",
                json={
                    "mode": "python",
                    "namespace": "default",
                    "table_name": "transactions_10k",
                    "python_script": "result_df = df[(df['amount'] > 2000) & (df['status'] == 'COMPLETED')]",
                    "limit": 50,
                },
                headers=_auth_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        # amount > 2000: 2500 (COMPLETED), 9999 (COMPLETED), 15000 (FAILED) -- the
        # status filter excludes the FAILED row, leaving 2.
        assert data["result"]["total_rows"] == 2

    def test_submit_invalid_mode(self, test_client):
        resp = test_client.post(
            "/v1/query/submit",
            json={"mode": "invalid_mode", "sql": "SELECT 1"},
            headers=_auth_headers(),
        )
        assert resp.status_code in (422, 400)

    def test_submit_sql_missing_fields(self, test_client):
        resp = test_client.post(
            "/v1/query/submit",
            json={"mode": "sql"},  # missing namespace, table_name, sql
            headers=_auth_headers(),
        )
        assert resp.status_code in (422, 400)

    def test_explain_endpoint(self, test_client, sample_arrow_table):
        from query_engine.sql_executor import SQLExecutor
        with patch.object(SQLExecutor, "_load_iceberg", return_value=sample_arrow_table):
            resp = test_client.post(
                "/v1/query/explain",
                json={
                    "mode": "sql",
                    "namespace": "default",
                    "table_name": "t",
                    "sql": "SELECT * FROM iceberg_table LIMIT 5",
                },
                headers=_auth_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "execution_plan" in data

    def test_history_endpoint_empty(self, test_client):
        resp = test_client.get("/v1/query/history", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_get_job_not_found(self, test_client):
        resp = test_client.get(f"/v1/query/{uuid.uuid4()}", headers=_auth_headers())
        assert resp.status_code == 404

    def test_unauthenticated_submit_returns_401(self, test_client):
        resp = test_client.post(
            "/v1/query/submit",
            json={"mode": "sql", "namespace": "default", "table_name": "t", "sql": "SELECT 1"},
        )
        assert resp.status_code == 401

    def test_multi_query_endpoint(self, test_client, sample_arrow_table):
        from query_engine.sql_executor import SQLExecutor
        with patch.object(SQLExecutor, "_load_iceberg", return_value=sample_arrow_table):
            resp = test_client.post(
                "/v1/query/multi",
                json={
                    "queries": [
                        {
                            "mode": "sql",
                            "namespace": "default",
                            "table_name": "t",
                            "sql": "SELECT COUNT(*) as cnt FROM iceberg_table",
                        }
                    ],
                    "merge_strategy": "union",
                },
                headers=_auth_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "jobs" in data
        assert len(data["jobs"]) == 1

    def test_multi_query_exceeds_limit(self, test_client):
        resp = test_client.post(
            "/v1/query/multi",
            json={
                "queries": [
                    {
                        "mode": "sql", "namespace": "default", "table_name": "t",
                        "sql": f"SELECT {i} as n",
                    }
                    for i in range(11)  # 11 > limit of 10
                ],
                "merge_strategy": "union",
            },
            headers=_auth_headers(),
        )
        assert resp.status_code == 400
