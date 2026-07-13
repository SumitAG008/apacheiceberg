# Copyright (c) 2025 Meldra AI Ltd. All rights reserved.
"""
query_engine/sql_backends.py — pluggable SQL execution backends.

SQLExecutor doesn't talk to DuckDB directly; it asks a SQLBackend to
register a table and run SQL. DuckDB is the only backend actually wired up
to real data today (DuckDBBackend below) — it's a genuine, fast, single-node
vectorized engine, and the honest state of this platform's "distributed
query engine" branding. Spark and Doris are real adapters with real client
libraries, but they need an actual cluster to point at, which nothing in
this repo's docker-compose.yml or kubernetes/ provisions yet. Selecting one
without a cluster configured raises immediately and explains exactly what's
missing, rather than silently returning wrong results.

Swapping in a real Spark or Doris cluster later is a config change
(QUERY_ENGINE_BACKEND + the backend's own env vars), not a rewrite of
sql_executor.py or the /v1/query/* API surface.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod

import pandas as pd


class SQLBackend(ABC):
    """One SQL execution backend: register tables, run SQL, explain it."""

    name: str = "unknown"

    @abstractmethod
    def register_table(self, alias: str, df: pd.DataFrame) -> None:
        """Make `df` queryable under `alias` for the next execute()/explain() call."""

    @abstractmethod
    def execute(self, sql: str) -> pd.DataFrame:
        """Run `sql` against every table registered so far, return a pandas DataFrame."""

    @abstractmethod
    def explain(self, sql: str) -> str:
        """Return this backend's query plan for `sql` as text."""

    def close(self) -> None:
        """Release backend resources (connection, session, ...). No-op by default."""


class DuckDBBackend(SQLBackend):
    """
    The real, working default: single-node vectorized DuckDB over data
    already materialised as pandas DataFrames (post-RBAC-enforcement).
    Needs no cluster to operate, and is genuinely fast for the data sizes
    an early lakehouse deployment sees.
    """

    name = "duckdb"

    def __init__(self) -> None:
        import duckdb
        self._duckdb = duckdb
        self.con = duckdb.connect(database=":memory:")
        self.con.execute("SET enable_external_access=false;")

    def register_table(self, alias: str, df: pd.DataFrame) -> None:
        self.con.register(alias, df)

    def execute(self, sql: str) -> pd.DataFrame:
        return self.con.execute(sql).fetchdf()

    def explain(self, sql: str) -> str:
        try:
            return self.con.execute(f"EXPLAIN {sql}").fetchdf().to_string(index=False)
        except Exception:
            return "Execution plan not available for this query."

    def close(self) -> None:
        self.con.close()

    @property
    def version(self) -> str:
        return self._duckdb.__version__


class SparkBackend(SQLBackend):
    """
    Adapter for a real Apache Spark cluster, via PySpark against a
    standalone/YARN/Kubernetes master. NOT wired up: there is no Spark
    cluster in this deployment's docker-compose.yml or kubernetes/
    manifests. To make this real:

      1. Add a Spark cluster (e.g. the `bitnami/spark` docker-compose
         images, or a managed cluster) and set SPARK_MASTER_URL, e.g.
         "spark://spark-master:7077".
      2. `pip install pyspark` in backend/requirements.txt.
      3. register_table()/execute() below already call the right PySpark
         APIs (createDataFrame + createOrReplaceTempView, spark.sql) —
         they just need a live SparkSession to run against.

    Raises NotImplementedError immediately if SPARK_MASTER_URL isn't set,
    rather than pretending to run distributed and silently using DuckDB.
    """

    name = "spark"

    def __init__(self) -> None:
        master = os.environ.get("SPARK_MASTER_URL")
        if not master:
            raise NotImplementedError(
                "QUERY_ENGINE_BACKEND=spark was selected, but SPARK_MASTER_URL isn't set — "
                "there's no Spark cluster wired into this deployment yet. See the SparkBackend "
                "docstring in query_engine/sql_backends.py for what's needed to make this real."
            )
        from pyspark.sql import SparkSession
        self.spark = SparkSession.builder.master(master).appName("meldra-dqe").getOrCreate()

    def register_table(self, alias: str, df: pd.DataFrame) -> None:
        self.spark.createDataFrame(df).createOrReplaceTempView(alias)

    def execute(self, sql: str) -> pd.DataFrame:
        return self.spark.sql(sql).toPandas()

    def explain(self, sql: str) -> str:
        return self.spark.sql(sql)._jdf.queryExecution().toString()

    def close(self) -> None:
        self.spark.stop()


class DorisBackend(SQLBackend):
    """
    Adapter for a real Apache Doris cluster (MPP OLAP), via its MySQL-wire
    protocol frontend. NOT wired up: there are no Doris FE/BE containers in
    this deployment yet. To make this real:

      1. Add Doris FE + BE services (the `apache/doris` docker images) to
         docker-compose.yml, and set DORIS_FE_HOST (+ optionally
         DORIS_FE_QUERY_PORT / DORIS_USER / DORIS_PASSWORD).
      2. `pip install pymysql` in backend/requirements.txt.
      3. register_table() needs a real cluster to test the load path
         against (CREATE TABLE + Stream Load HTTP API is the standard
         approach for bulk loading a DataFrame) — deliberately left
         unimplemented rather than guessed at without a cluster to verify
         against.

    Raises NotImplementedError immediately if DORIS_FE_HOST isn't set.
    """

    name = "doris"

    def __init__(self) -> None:
        host = os.environ.get("DORIS_FE_HOST")
        if not host:
            raise NotImplementedError(
                "QUERY_ENGINE_BACKEND=doris was selected, but DORIS_FE_HOST isn't set — "
                "there's no Doris cluster wired into this deployment yet. See the DorisBackend "
                "docstring in query_engine/sql_backends.py for what's needed to make this real."
            )
        import pymysql
        self.conn = pymysql.connect(
            host=host,
            port=int(os.environ.get("DORIS_FE_QUERY_PORT", "9030")),
            user=os.environ.get("DORIS_USER", "root"),
            password=os.environ.get("DORIS_PASSWORD", ""),
        )

    def register_table(self, alias: str, df: pd.DataFrame) -> None:
        raise NotImplementedError(
            "Doris table registration needs a real cluster to implement and test the Stream "
            "Load path against — see the DorisBackend docstring in query_engine/sql_backends.py."
        )

    def execute(self, sql: str) -> pd.DataFrame:
        with self.conn.cursor() as cur:
            cur.execute(sql)
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
        return pd.DataFrame(rows, columns=cols)

    def explain(self, sql: str) -> str:
        with self.conn.cursor() as cur:
            cur.execute(f"EXPLAIN {sql}")
            return "\n".join(str(r) for r in cur.fetchall())

    def close(self) -> None:
        self.conn.close()


_BACKENDS = {
    "duckdb": DuckDBBackend,
    "spark": SparkBackend,
    "doris": DorisBackend,
}


def available_backends() -> list[dict]:
    """Every backend name this build knows about, and whether it's actually
    usable right now (real for duckdb; needs cluster env vars for the rest)."""
    return [
        {
            "name": "duckdb",
            "status": "active",
            "description": "Single-node vectorized SQL — the real, working default.",
        },
        {
            "name": "spark",
            "status": "active" if os.environ.get("SPARK_MASTER_URL") else "not_configured",
            "description": "Distributed SQL via a real Spark cluster. Needs SPARK_MASTER_URL.",
        },
        {
            "name": "doris",
            "status": "active" if os.environ.get("DORIS_FE_HOST") else "not_configured",
            "description": "MPP OLAP via a real Doris cluster. Needs DORIS_FE_HOST.",
        },
    ]


def get_sql_backend() -> SQLBackend:
    """Instantiate the backend named by QUERY_ENGINE_BACKEND (default: duckdb)."""
    name = os.environ.get("QUERY_ENGINE_BACKEND", "duckdb").lower()
    cls = _BACKENDS.get(name)
    if cls is None:
        raise ValueError(f"Unknown QUERY_ENGINE_BACKEND '{name}'. Valid values: {', '.join(_BACKENDS)}")
    return cls()
