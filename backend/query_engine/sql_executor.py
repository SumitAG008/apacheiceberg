# Copyright (c) 2025 Meldra AI Ltd. All rights reserved.
"""
query_engine/sql_executor.py — SQL execution engine.

Loads Apache Iceberg tables via PyIceberg, registers them with a pluggable
SQLBackend (DuckDB by default — see sql_backends.py for how Spark/Doris
plug into the same interface once a real cluster exists), executes
arbitrary SQL with predicate pushdown, and returns normalised QueryResult
objects.

Supports:
  - Single-table queries
  - Multi-table cross-namespace joins (each table registered as a view)
  - Predicate pushdown via Iceberg row filter
  - EXPLAIN plan extraction
  - Row-level pagination / truncation detection
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

import pandas as pd
import pyarrow as pa

from query_engine.models import QueryJob, QueryResult
from query_engine.sql_backends import get_sql_backend

logger = logging.getLogger(__name__)

# Safe scalar types for JSON serialisation
_SAFE_TYPES = (str, int, float, bool, type(None))


def _safe_val(v: Any) -> Any:
    """Convert non-JSON-safe values to strings."""
    if v is None:
        return None
    if isinstance(v, _SAFE_TYPES):
        return v
    if hasattr(v, "item"):        # numpy scalar
        return v.item()
    if isinstance(v, float) and pd.isna(v):
        return None
    return str(v)


def _sanitise_rows(df: pd.DataFrame) -> List[Dict[str, Any]]:
    rows = df.to_dict(orient="records")
    return [{k: _safe_val(v) for k, v in row.items()} for row in rows]


class SQLExecutor:
    """
    Executes DuckDB SQL queries against one or more Apache Iceberg tables.

    The primary table is always registered as 'iceberg_table' (backwards
    compat with existing tools). Additional tables can be referenced by their
    fully-qualified name (namespace__table_name) once included in `extra_tables`.
    """

    def execute(self, job: QueryJob) -> QueryResult:
        """Run the SQL job synchronously and return a QueryResult."""
        t0 = time.perf_counter()

        catalog = self._get_catalog()
        backend = get_sql_backend()
        try:
            # ── 1. Register primary Iceberg table ──────────────────────────────
            # The catalog read uses the tenant-scoped namespace; job.namespace
            # stays the client-facing name for RBAC matching and display below.
            from tenancy import scope_namespace
            scoped_ns = scope_namespace(job.tenant_id, job.namespace) if job.tenant_id else job.namespace
            primary_arrow = self._load_iceberg(catalog, scoped_ns, job.table_name, job.filters)

            # Enforce full RBAC (table access, row filtering, column masking/
            # denial) at the data layer before the backend ever sees the data —
            # aliasing in the SQL cannot expose the real values, and a role
            # with no access to this table gets TableAccessDenied propagated
            # as a failed job (caught by the executor's run loop) rather than
            # data.
            from rbac_utils import enforce_rbac
            primary_df = enforce_rbac(
                primary_arrow.to_pandas(), job.namespace, job.table_name, job.role
            )
            backend.register_table("iceberg_table", primary_df)

            # Also register with fully-qualified alias so multi-table joins work
            fq_name = f"{job.namespace}__{job.table_name}"
            backend.register_table(fq_name, primary_df)

            # ── 2. Execution plan (EXPLAIN) ─────────────────────────────────────
            explain_text = backend.explain(job.sql)
            engine_label = f"{backend.name} {backend.version}" if hasattr(backend, "version") else backend.name
            plan_note = (
                f"[DQE/SQL] Engine: {engine_label} | "
                f"Table: {job.namespace}.{job.table_name} | "
                f"Source rows scanned: {len(primary_arrow)}\n\n"
                f"{explain_text}"
            )

            # ── 3. Execute query ────────────────────────────────────────────────
            result_df: pd.DataFrame = backend.execute(job.sql)

            duration_ms = int((time.perf_counter() - t0) * 1000)

            # ── 4. Pagination & truncation ──────────────────────────────────────
            total_rows = len(result_df)
            truncated = total_rows > job.limit
            if truncated:
                result_df = result_df.head(job.limit)

            rows = _sanitise_rows(result_df)
            columns = list(result_df.columns)

            logger.info(
                "[SQLExecutor] job=%s engine=%s rows=%d truncated=%s duration=%dms",
                job.job_id, backend.name, total_rows, truncated, duration_ms,
            )

            return QueryResult(
                columns=columns,
                rows=rows,
                total_rows=total_rows,
                truncated=truncated,
                execution_plan=plan_note,
                engine_used=backend.name,
                duration_ms=duration_ms,
            )
        finally:
            backend.close()

    def explain(self, job: QueryJob) -> str:
        """Return the backend's EXPLAIN plan without executing the full query."""
        backend = get_sql_backend()
        try:
            from tenancy import scope_namespace
            catalog = self._get_catalog()
            scoped_ns = scope_namespace(job.tenant_id, job.namespace) if job.tenant_id else job.namespace
            primary_arrow = self._load_iceberg(catalog, scoped_ns, job.table_name, job.filters)
            backend.register_table("iceberg_table", primary_arrow.to_pandas())
            return backend.explain(job.sql)
        except Exception as exc:
            return f"[SQLExecutor/EXPLAIN] Could not compute plan: {exc}"
        finally:
            backend.close()

    # ─── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _get_catalog():
        import sys, os
        backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if backend_root not in sys.path:
            sys.path.insert(0, backend_root)
        from catalog_setup import get_catalog
        return get_catalog()

    @staticmethod
    def _load_iceberg(
        catalog,
        namespace: str,
        table_name: str,
        filters: Optional[Dict[str, Any]],
    ) -> pa.Table:
        """Load an Iceberg table, optionally applying column equality filters."""
        identifier = (namespace, table_name)
        try:
            table = catalog.load_table(identifier)
        except Exception as exc:
            raise ValueError(f"Iceberg table '{namespace}.{table_name}' not found: {exc}") from exc

        scan = table.scan()

        # Pushdown equality filters using PyIceberg expressions
        if filters:
            try:
                from pyiceberg.expressions import (
                    EqualTo, And
                )
                expr = None
                for col, val in filters.items():
                    eq = EqualTo(col, val)
                    expr = eq if expr is None else And(expr, eq)
                if expr is not None:
                    scan = table.scan(row_filter=expr)
            except Exception as fe:
                logger.warning(
                    "[SQLExecutor] Predicate pushdown failed (%s); falling back to full scan", fe
                )

        return scan.to_arrow()
