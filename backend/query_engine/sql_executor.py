# Copyright (c) 2025 Meldra AI Ltd. All rights reserved.
"""
query_engine/sql_executor.py — SQL execution engine.

Loads Apache Iceberg tables via PyIceberg, registers them with a pluggable
SQLBackend (DuckDB by default — see sql_backends.py for how Spark/Doris
plug into the same interface once a real cluster exists), executes SQL,
and returns normalised QueryResult objects.

Supports:
  - Single-table queries
  - Multi-table cross-namespace joins (each table registered as a view)
  - Scan pushdown (Iceberg row_filter + column projection) when the caller
    supplies `job.filters` / `job.projection`. NOTE: predicates written
    inline in the SQL WHERE clause are NOT auto-translated into Iceberg
    expressions — they are evaluated by the backend after the scan. Callers
    that need file/partition pruning must populate `job.filters`. See
    docs/technical/TD-004-scan-pushdown.md for the roadmap to SQL-derived
    pushdown.
  - Zero-copy Arrow registration when no RBAC transform applies
  - EXPLAIN plan extraction
  - Row-level pagination / truncation detection
"""

from __future__ import annotations

import logging
import os
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


# ─── Tenant scope guard (defence in depth) ────────────────────────────────

def assert_tenant_scoped(job, engine: str) -> None:
    """Refuse to run a data-touching job that carries no tenant.

    tenant_id="" disables namespace scoping in scope_namespace(), so an
    unscoped job reads the raw client-supplied namespace. That is correct
    for direct/library callers and the test suite, and is a confidentiality
    bug for anything reachable by a user. This is the backstop that made
    SEC-2026-001 possible: the isolation logic existed and simply was not
    being passed a tenant, and nothing complained.

    Every unscoped execution is audited unconditionally. Whether it is also
    *refused* is controlled by MELDRA_REQUIRE_TENANT_SCOPE, which defaults
    to enabled whenever MELDRA_ENV is not a local/dev/test environment —
    i.e. production fails closed, local development stays usable.
    """
    if getattr(job, "tenant_id", ""):
        return

    from observability.audit_log import audit

    env = os.environ.get("MELDRA_ENV", "development").lower()
    default_required = env not in ("development", "dev", "local", "test", "ci")
    required = os.environ.get(
        "MELDRA_REQUIRE_TENANT_SCOPE", "1" if default_required else "0"
    ) == "1"

    audit.deny(
        "query.tenant_scope",
        reason="job carried no tenant_id; namespace scoping was skipped",
        role=getattr(job, "role", ""),
        subject=getattr(job, "submitted_by", "") or "",
        resource=f"{getattr(job, 'namespace', '')}.{getattr(job, 'table_name', '')}",
        request_id=getattr(job, "job_id", ""),
        detail={"engine": engine, "enforced": required, "env": env},
    )

    if required:
        raise PermissionError(
            "Refusing to execute an unscoped query: no tenant_id on the job. "
            "See docs/security/SEC-2026-001-agent-tenant-bypass.md."
        )


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

        assert_tenant_scoped(job, "sql")
        catalog = self._get_catalog()
        backend = get_sql_backend()
        try:
            # ── 1. Register primary Iceberg table ──────────────────────────────
            # The catalog read uses the tenant-scoped namespace; job.namespace
            # stays the client-facing name for RBAC matching and display below.
            from tenancy import scope_namespace
            scoped_ns = scope_namespace(job.tenant_id, job.namespace) if job.tenant_id else job.namespace
            primary_arrow = self._load_iceberg(
                catalog, scoped_ns, job.table_name, job.filters, job.projection
            )

            # Enforce full RBAC (table access, row filtering, column masking/
            # denial) at the data layer before the backend ever sees the data —
            # aliasing in the SQL cannot expose the real values, and a role
            # with no access to this table gets TableAccessDenied propagated
            # as a failed job (caught by the executor's run loop) rather than
            # data.
            from rbac_utils import enforce_rbac, rbac_is_noop

            # ZERO-COPY FAST PATH: if this role has no row filter, column
            # mask or deny policy for this table, there is nothing to
            # transform — hand the Arrow table straight to the backend.
            # DuckDB scans Arrow buffers in place, so we skip a full
            # materialised pandas copy of the dataset (previously ~2x peak
            # RSS on every query, which contradicted the product's
            # zero-copy positioning). check_table_access still runs, so an
            # unauthorised role is still refused on this path.
            if rbac_is_noop(job.namespace, job.table_name, job.role):
                registered = primary_arrow
                copy_mode = "arrow-zero-copy"
            else:
                registered = enforce_rbac(
                    primary_arrow.to_pandas(), job.namespace, job.table_name, job.role
                )
                copy_mode = "pandas-rbac-materialised"

            # Register ONCE under both names. register_view aliases the
            # already-registered relation instead of shipping the payload a
            # second time (the previous code called register_table twice
            # with the same frame, doubling the copy).
            backend.register_table("iceberg_table", registered)
            fq_name = f"{job.namespace}__{job.table_name}"
            backend.register_view(fq_name, "iceberg_table")

            # ── 2. Execution plan (EXPLAIN) ─────────────────────────────────────
            explain_text = backend.explain(job.sql)
            engine_label = f"{backend.name} {backend.version}" if hasattr(backend, "version") else backend.name
            plan_note = (
                f"[DQE/SQL] Engine: {engine_label} | "
                f"Table: {job.namespace}.{job.table_name} | "
                f"Source rows scanned: {len(primary_arrow)} | "
                f"Materialisation: {copy_mode}\n\n"
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

            from observability.audit_log import audit
            audit.allow(
                "query.execute",
                tenant_id=job.tenant_id,
                role=job.role,
                subject=job.submitted_by or "",
                resource=f"{job.namespace}.{job.table_name}",
                request_id=job.job_id,
                detail={
                    "mode": "sql",
                    "engine": backend.name,
                    "materialisation": copy_mode,
                    "source_rows_scanned": len(primary_arrow),
                    "rows_returned": len(rows),
                    "truncated": truncated,
                    "duration_ms": duration_ms,
                },
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
            assert_tenant_scoped(job, "sql_explain")
            from tenancy import scope_namespace
            catalog = self._get_catalog()
            scoped_ns = scope_namespace(job.tenant_id, job.namespace) if job.tenant_id else job.namespace
            primary_arrow = self._load_iceberg(
                catalog, scoped_ns, job.table_name, job.filters, job.projection
            )
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
        projection: Optional[List[str]] = None,
    ) -> pa.Table:
        """Load an Iceberg table with row-filter and column-projection pushdown.

        Both are applied at scan planning time, so Iceberg can prune whole
        manifests / data files before any bytes are read. A failure in either
        degrades to a full scan rather than to wrong results, and is logged
        at WARNING with the reason.
        """
        identifier = (namespace, table_name)
        try:
            table = catalog.load_table(identifier)
        except Exception as exc:
            raise ValueError(f"Iceberg table '{namespace}.{table_name}' not found: {exc}") from exc

        scan_kwargs: Dict[str, Any] = {}

        # ── Row filter pushdown (partition + file pruning) ──────────────
        if filters:
            try:
                from pyiceberg.expressions import EqualTo, And
                expr = None
                for col, val in filters.items():
                    eq = EqualTo(col, val)
                    expr = eq if expr is None else And(expr, eq)
                if expr is not None:
                    scan_kwargs["row_filter"] = expr
            except Exception as fe:
                logger.warning(
                    "[SQLExecutor] Row-filter pushdown failed (%s); falling back to full scan", fe
                )

        # ── Column projection pushdown (avoids reading unused columns) ──
        if projection:
            try:
                available = {f.name for f in table.schema().fields}
                selected = [c for c in projection if c in available]
                if selected:
                    scan_kwargs["selected_fields"] = tuple(selected)
            except Exception as pe:
                logger.warning(
                    "[SQLExecutor] Projection pushdown failed (%s); reading all columns", pe
                )

        return table.scan(**scan_kwargs).to_arrow()
