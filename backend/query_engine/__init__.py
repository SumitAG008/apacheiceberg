# Copyright (c) 2025 Meldra AI Ltd. All rights reserved.
# This software is proprietary and confidential. Unauthorised use is prohibited.
"""
query_engine — Distributed Query Engine for Apache Iceberg

Supports three extraction modes:
  - SQL    : DuckDB over PyIceberg tables (multi-table joins, predicate pushdown)
  - GRAPH  : real openCypher via Apache AGE; graph algorithms via NetworkX
  - PYTHON : AST-safe pandas/pyarrow transformation scripts

Public API:
    from query_engine import QueryEngine, QueryJob, QueryMode, QueryResult, QueryStatus
"""

from query_engine.models import QueryJob, QueryMode, QueryResult, QueryStatus
from query_engine.executor import QueryEngine

__all__ = [
    "QueryEngine",
    "QueryJob",
    "QueryMode",
    "QueryResult",
    "QueryStatus",
]
