# ADR-0002 — Namespace-prefix tenant isolation with context-bound binding

**Status:** Accepted · **Date:** 2026-09-05 · **Supersedes:** implicit prior model
**Related:** SEC-2026-001

## Context

Multi-tenant SaaS over a shared Iceberg catalog. A tenant must never see,
list, reference or guess its way into another tenant's data.

## Options

| Option | Assessment |
|---|---|
| Catalog per tenant | Strongest isolation; heavy operationally; expensive at low tenant sizes |
| **Namespace prefixing in a shared catalog** | Good isolation; simple; cheap; needs disciplined enforcement |
| Row-level tenant column | Weakest; one missing predicate leaks everything |

## Decision

Shared catalog with silent namespace prefixing (`t_<tenant>__<namespace>`),
translated at the API boundary. `tenant_id` derives **only** from the JWT
`sub` claim.

Reinforced by three mechanisms after SEC-2026-001:

1. **Context binding** — agent tools read tenant and role from ContextVars
   set server-side, never from LLM-visible tool arguments.
2. **Fail-closed guard** — `assert_tenant_scoped()` refuses unscoped
   data-touching jobs; enforced by default outside dev/test.
3. **CI enforcement** — an AST test fails the build if any `QueryJob` is
   constructed without explicit `tenant_id` and `role`.

## Rationale

The original design was correct. It failed because correctness depended on
every caller remembering to pass a parameter, and one path did not — the
one the agent's system prompt told the model to prefer.

This is the substance of principle **P2**: a tenant boundary enforced by
convention is not a boundary. The three mechanisms above move enforcement
from "a reviewer notices" to "the build fails and the executor refuses."

Context binding also has a security property beyond tidiness: because the
model never sees tenant as a tool parameter, a prompt-injected instruction
cannot cause it to name a tenant it does not belong to. The agent is
structurally unable to cross tenants rather than instructed not to.

## Consequences

**Positive:** cheap; boundary is testable; agent is injection-resistant on
this axis.

**Negative:** one account = one tenant, so teams and organisations need a
model extension; graph access via Apache AGE is not yet covered (GAP-02);
`MELDRA_REQUIRE_TENANT_SCOPE=0` can still disable enforcement, mitigated by
unconditional auditing.
