# Copyright (c) 2025 Meldra AI Ltd. All rights reserved.
"""
query_engine/models.py — Pydantic data models for the Distributed Query Engine.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


# ─── Enumerations ─────────────────────────────────────────────────────────────

class QueryMode(str, Enum):
    SQL    = "sql"     # DuckDB over Apache Iceberg tables
    GRAPH  = "graph"   # openCypher via Apache AGE, algorithms via NetworkX
    PYTHON = "python"  # Safe pandas/pyarrow extraction scripts


class QueryStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED  = "failed"


# ─── Result ───────────────────────────────────────────────────────────────────

class QueryResult(BaseModel):
    """The normalised output of any query engine execution."""
    columns: List[str]
    rows: List[Dict[str, Any]]
    total_rows: int
    truncated: bool = False
    execution_plan: Optional[str] = None     # EXPLAIN text or routing note
    engine_used: Optional[str] = None        # "duckdb", "networkx", "python_exec"
    duration_ms: Optional[int] = None


# ─── Core Models ──────────────────────────────────────────────────────────────

class QueryJob(BaseModel):
    """
    Unified job model passed to QueryEngine.submit() or created by the REST layer.
    """
    job_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    mode: QueryMode

    # SQL mode
    namespace: Optional[str] = None
    table_name: Optional[str] = None
    sql: Optional[str] = None

    # GRAPH mode
    graph_name: Optional[str] = None
    cypher: Optional[str] = None
    algorithm: Optional[str] = None   # 'pagerank' | 'betweenness_centrality' | etc.

    # PYTHON mode
    python_script: Optional[str] = None

    # Pushdown filter predicates (applied at Iceberg scan planning time,
    # before any data file is read). Equality only for now.
    filters: Optional[Dict[str, Any]] = None

    # Column projection pushdown — restrict the Iceberg scan to these
    # columns. Unknown column names are dropped rather than raising, so a
    # stale projection degrades to reading more data, never to an error.
    projection: Optional[List[str]] = None

    # Metadata (set by engine)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    status: QueryStatus = QueryStatus.PENDING
    result: Optional[QueryResult] = None
    error: Optional[str] = None
    submitted_by: Optional[str] = None   # user ID from JWT
    # RBAC role of the submitting user — set server-side from the JWT payload
    # ONLY (never from client-supplied request fields), used to enforce
    # column-level masking/denial at the data layer before execution.
    role: str = "Business Analyst"
    # Tenant (= submitting user's own account id), set server-side ONLY.
    # Executors use this to translate `namespace`/`graph_name` into the real,
    # tenant-scoped catalog namespace before touching the catalog — RBAC and
    # everything else in this job continues to use the client-facing
    # (unscoped) name, exactly as the submitter typed it.
    tenant_id: str = ""

    @model_validator(mode="after")
    def _validate_mode_fields(self) -> "QueryJob":
        if self.mode == QueryMode.SQL:
            if not self.sql:
                raise ValueError("'sql' is required for SQL mode")
            if not self.namespace or not self.table_name:
                raise ValueError("'namespace' and 'table_name' are required for SQL mode")
        elif self.mode == QueryMode.GRAPH:
            if not self.cypher and not self.algorithm:
                raise ValueError("'cypher' or 'algorithm' is required for GRAPH mode")
            if not self.graph_name:
                raise ValueError("'graph_name' is required for GRAPH mode")
        elif self.mode == QueryMode.PYTHON:
            if not self.python_script:
                raise ValueError("'python_script' is required for PYTHON mode")
            if not self.namespace or not self.table_name:
                raise ValueError("'namespace' and 'table_name' are required for PYTHON mode")
        return self


# ─── REST request / response shapes ──────────────────────────────────────────

class QuerySubmitRequest(BaseModel):
    """Incoming payload for POST /v1/query/submit"""
    mode: QueryMode

    # SQL
    namespace: Optional[str] = None
    table_name: Optional[str] = None
    sql: Optional[str] = None

    # GRAPH
    cypher: Optional[str] = None
    graph_name: Optional[str] = None
    algorithm: Optional[str] = None

    # PYTHON
    python_script: Optional[str] = None

    filters: Optional[Dict[str, Any]] = None
    limit: int = Field(default=1000, ge=1, le=50_000)


class QuerySubmitResponse(BaseModel):
    job_id: str
    status: QueryStatus
    message: str


class QueryStatusResponse(BaseModel):
    job_id: str
    mode: QueryMode
    status: QueryStatus
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    result: Optional[QueryResult] = None
    error: Optional[str] = None


class QueryExplainRequest(BaseModel):
    """Dry-run — return execution plan without executing."""
    mode: QueryMode
    namespace: Optional[str] = None
    table_name: Optional[str] = None
    sql: Optional[str] = None
    cypher: Optional[str] = None
    graph_name: Optional[str] = None
    python_script: Optional[str] = None


class QueryExplainResponse(BaseModel):
    mode: str
    execution_plan: str
    estimated_cost: Optional[str] = None


class MultiQueryRequest(BaseModel):
    """Fan-out multiple queries and merge their results."""
    queries: List[QuerySubmitRequest]
    merge_strategy: str = "union"     # "union" | "join_on_key"
    join_key: Optional[str] = None


class MultiQueryResponse(BaseModel):
    job_ids: List[str]
    merged_result: Optional[QueryResult] = None
    status: str
