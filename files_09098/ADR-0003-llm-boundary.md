# ADR-0003 — The LLM boundary: models interpret, engines compute

**Status:** Accepted · **Date:** 2026-09-05 · **Deciders:** Architecture
**Related:** Principle P4

## Context

The platform's differentiator is natural-language access to grid data. It
is also used for settlement, billing and regulatory reporting, where a
wrong number is a regulatory event rather than a bad user experience.

## Decision

**The language model may generate queries. It may never generate values.**

| Model may | Model may not |
|---|---|
| Interpret intent | Compute an aggregate |
| Emit SQL, Cypher, or a transform script | State a figure not returned by an engine |
| Explain a returned result | Estimate, fill, or infer a missing value |
| Suggest a table or column | Decide authorisation |

Every number reaching a user is produced by DuckDB, Iceberg or NetworkX and
is reproducible by re-running the emitted query against the recorded
snapshot.

## Rationale

Language models are excellent at translating a domain question into a
query, and structurally unsuited to arithmetic over billions of rows. The
failure mode is the problem: a wrong query usually errors, while a
hallucinated figure looks exactly like a right one. In a settlement
context, the second is undetectable until a reconciliation fails months
later.

This also makes the platform defensible under audit. "Here is the SQL, here
is the snapshot ID, re-run it" is an answer a regulator accepts. "The AI
said so" is not.

## Consequences

**Positive:** results are reproducible and auditable; hallucination cannot
reach a settlement figure; the boundary is easy to explain to a compliance
audience and is a genuine differentiator against tools that let the model
answer directly.

**Negative:** forecasting and imputation are out of scope for the agent
path; the agent is only as good as the SQL it emits, so schema quality and
column naming become product concerns.

**Implementation obligations:**
- The UI must show the emitted query alongside the result.
- Query results must return their Iceberg snapshot ID (GAP-08).
- The agent system prompt must never invite the model to compute.
