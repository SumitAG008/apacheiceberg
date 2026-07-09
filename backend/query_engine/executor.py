# Copyright (c) 2025 Meldra AI Ltd. All rights reserved.
"""
query_engine/executor.py — Top-level QueryEngine router.

Routes QueryJob objects to the correct execution engine (SQL, Graph, Python)
based on job.mode. Manages async job lifecycle using the module-level JobStore
and executes engines in a thread pool to avoid blocking the FastAPI event loop.
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import List, Optional

from query_engine.job_store import job_store
from query_engine.models import QueryJob, QueryMode, QueryResult, QueryStatus
from query_engine.sql_executor import SQLExecutor
from query_engine.graph_executor import GraphExecutor
from query_engine.python_executor import PythonExecutor

logger = logging.getLogger(__name__)

# Shared thread pool — up to 8 concurrent query executions
_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="dqe-worker")


class QueryEngine:
    """
    Distributed Query Engine — routes jobs to SQL / Graph / Python executors.

    Usage (async FastAPI endpoint):
        engine = QueryEngine()
        job = await engine.submit(job)      # non-blocking
        job = engine.get(job_id)            # poll status

    Usage (LangChain tool, synchronous):
        engine = QueryEngine()
        job = engine.submit_sync(job)
    """

    def __init__(self) -> None:
        self._sql     = SQLExecutor()
        self._graph   = GraphExecutor()
        self._python  = PythonExecutor()

    # ─── Public async API (FastAPI) ───────────────────────────────────────────

    async def submit(self, job: QueryJob) -> QueryJob:
        """
        Register the job, kick off async execution, and return immediately
        with status=RUNNING. The caller should poll GET /v1/query/{job_id}.
        """
        job.status = QueryStatus.RUNNING
        job.started_at = datetime.utcnow()
        job_store.create(job)

        loop = asyncio.get_event_loop()
        loop.run_in_executor(_POOL, self._run_job, job.job_id)

        return job

    async def submit_and_wait(self, job: QueryJob) -> QueryJob:
        """
        Submit and block until execution completes (for small/fast queries).
        """
        job.status = QueryStatus.RUNNING
        job.started_at = datetime.utcnow()
        job_store.create(job)

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(_POOL, self._run_job, job.job_id)

        return job_store.get(job.job_id) or job

    def submit_sync(self, job: QueryJob) -> QueryJob:
        """Synchronous execution — for LangChain tool calls."""
        job.status = QueryStatus.RUNNING
        job.started_at = datetime.utcnow()
        job_store.create(job)
        self._run_job(job.job_id)
        return job_store.get(job.job_id) or job

    def get(self, job_id: str) -> Optional[QueryJob]:
        """Retrieve a job by ID."""
        return job_store.get(job_id)

    def list_for_user(self, user_id: str, limit: int = 50) -> List[QueryJob]:
        return job_store.list_for_user(user_id, limit=limit)

    def list_all(self, limit: int = 100) -> List[QueryJob]:
        return job_store.list_all(limit=limit)

    def explain(self, job: QueryJob) -> str:
        """Return execution plan text without running the query."""
        try:
            if job.mode == QueryMode.SQL:
                return self._sql.explain(job)
            elif job.mode == QueryMode.GRAPH:
                return self._graph.explain(job)
            elif job.mode == QueryMode.PYTHON:
                return self._python.explain(job)
        except Exception as exc:
            return f"[QueryEngine/EXPLAIN] Error: {exc}"

    @staticmethod
    def supported_modes() -> List[dict]:
        return [
            {
                "mode": "sql",
                "description": "Execute DuckDB SQL against Apache Iceberg tables",
                "required_fields": ["namespace", "table_name", "sql"],
                "optional_fields": ["filters", "limit"],
                "example_sql": "SELECT account_from, SUM(amount) FROM iceberg_table GROUP BY 1 ORDER BY 2 DESC LIMIT 10",
            },
            {
                "mode": "graph",
                "description": "Cypher-like pattern matching or graph algorithms on the PostgreSQL graph store",
                "required_fields": ["graph_name"],
                "optional_fields": ["cypher", "algorithm", "filters", "limit"],
                "supported_algorithms": [
                    "pagerank", "betweenness_centrality", "degree_centrality",
                    "connected_components", "find_cycles", "shortest_path",
                    "community_detection",
                ],
                "example_cypher": "MATCH (a)-[r]->(b) RETURN a.node_id, b.node_id LIMIT 20",
            },
            {
                "mode": "python",
                "description": "AST-safe pandas/pyarrow transformation script",
                "required_fields": ["namespace", "table_name", "python_script"],
                "optional_fields": ["filters", "limit"],
                "available_in_scope": ["df", "arrow_table", "pd", "pa", "duckdb", "json", "datetime", "re", "math"],
                "output_contract": "Script must set result_df = <pandas DataFrame>",
                "example_script": "result_df = df[df['amount'] > 5000].groupby('account_from')['amount'].sum().reset_index()",
            },
        ]

    # ─── Internal execution ───────────────────────────────────────────────────

    def _run_job(self, job_id: str) -> None:
        """
        Execute the job synchronously (called inside thread pool).
        Updates job status in the store on completion or failure.
        """
        job = job_store.get(job_id)
        if job is None:
            logger.error("[QueryEngine] Job %s not found in store", job_id)
            return

        try:
            logger.info("[QueryEngine] Executing job %s mode=%s", job_id, job.mode)
            result: QueryResult

            if job.mode == QueryMode.SQL:
                result = self._sql.execute(job)
            elif job.mode == QueryMode.GRAPH:
                result = self._graph.execute(job)
            elif job.mode == QueryMode.PYTHON:
                result = self._python.execute(job)
            else:
                raise ValueError(f"Unsupported query mode: {job.mode}")

            job.status = QueryStatus.SUCCESS
            job.result = result
            job.completed_at = datetime.utcnow()
            if result.duration_ms is not None:
                pass  # already set by executor

            logger.info(
                "[QueryEngine] Job %s SUCCESS rows=%d engine=%s",
                job_id, result.total_rows, result.engine_used,
            )

        except Exception as exc:
            logger.exception("[QueryEngine] Job %s FAILED: %s", job_id, exc)
            job.status = QueryStatus.FAILED
            job.error = str(exc)
            job.completed_at = datetime.utcnow()

        finally:
            job_store.update(job)


# Module-level singleton — shared across FastAPI and tool layer
query_engine = QueryEngine()
