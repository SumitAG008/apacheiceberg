# ADR-0001 — Apache Iceberg as the table format

**Status:** Accepted · **Date:** 2026-09-05 · **Deciders:** Architecture

## Context

Grid and metering data is high-volume, long-retention and subject to
schema change over decades. The platform needs ACID commits, time travel,
schema evolution, and freedom from vendor lock-in across a 20–40 year asset
lifecycle.

## Options

| Option | Assessment |
|---|---|
| **Apache Iceberg** | Hidden partitioning; broad multi-engine support (Spark, Trino, Dremio, DuckDB, Snowflake, BigQuery); snapshot isolation; mature Python client |
| Delta Lake | Strong, but engine ecosystem is Databricks-centred |
| Apache Hudi | Good upserts; smaller ecosystem, more operational complexity |
| Raw Parquet + Hive | No ACID, no schema evolution, no time travel |
| Cloud warehouse | Proprietary storage; cost scales badly at this volume; exit is expensive |

## Decision

Apache Iceberg on object storage, accessed via PyIceberg, catalogued in
AWS Glue or an Iceberg REST catalog.

## Rationale

**Hidden partitioning** is the decisive feature for this user base. Analysts
write `WHERE reading_ts > '2026-09-01'` and get pruning without knowing a
partition column exists. In a utility, the people who ask the best questions
are rarely the people fluent in partition layouts.

**Snapshot isolation** gives the reproducible as-of query that settlement
disputes and regulatory responses require. "What did the data say on 14
March" must be answerable identically in September.

**Multi-engine reach** satisfies principle P3. A DNO can read its own data
with Spark or Trino tomorrow without Meldra in the path, which is what makes
the platform procurable rather than a lock-in risk.

## Consequences

**Positive:** open exit path; storage/compute separation; time travel is
free rather than engineered.

**Negative:** small-file management is now the operator's problem
(see GAP-10); PyIceberg lags the Java implementation on some features;
snapshot growth needs governed expiry (ARC-003 §5).

**Neutral:** commits to object storage as the substrate.
