# Claims Register

Every statement made outside the team (website, decks, emails, docs, demos) about what the platform
does. Owned by `gtm-lead`, evidence supplied by `cto`, checked weekly by `auditor`.

**Rule:** a claim goes into external material only when its status is ✅ Proven. 🟡 claims may
appear only with the qualifier shown. ❌ claims must not be made.

| ID | Claim (exact wording) | Status | Evidence (test / file:line / CI run) | Allowed qualifier | Where used | Last verified |
|---|---|---|---|---|---|---|
| CLM-001 | "Detects post-hoc modifications and sequence gaps" | UNVERIFIED | To be confirmed by first audit (candidates: `backend/tests/test_omission_demo.py`, `test_verifier_rigor.py`) | — | PROJECT_PLAN.md draft | — |
| CLM-002 | "Tamper-proof" | ❌ Not yet | The plan draft says not until milestone M1 (signature + RFC 3161 verification) is done | Say "tamper-evident" only once CLM-001 is proven | **Still used:** `ETP_PRODUCT_OVERVIEW.md:13`, `BC-002-etp-business-case.md:189`. Reword by 2026-10-10 or CI blocks | 2026-09-26 |
| CLM-003 | "Built on Apache Iceberg" (never "meldra Iceberg") | UNVERIFIED | Trademark guidance in SESSION_LOG.md; implementation evidence to be cited | — | help.meldra.ai | — |
| CLM-004 | "Certified tables" / "certified settlement reports" | UNVERIFIED | No certification body or scheme identified. If it means "curated / approved datasets", say that | "approved" or "verified" once CLM-001 is proven | `product_blueprint.md:21,44`. Reword by 2026-10-10 or CI blocks | 2026-09-26 |
| CLM-005 | "9,254 blocks/sec" | 🟡 Partial | Single-thread crypto path only (PROJECT_PLAN.md §3.2). No end-to-end (Kafka → verify → Iceberg), multi-thread or multi-gateway measurement exists; `cpp/bench/bench_etp_core.cpp` doesn't time signature verification | "single thread, verification path only, not end-to-end" | `MSG-001-messaging-pack.md:19` | 2026-09-26 |
| CLM-006 | "35,000+ verifications/sec per core · Sub-25 μs gateway verification latency" | ❌ Not yet | Not measured: no benchmark times verification. Spec is marked "Approved Specification" | Must not be quoted; state as a target only | `CPP-ARC-001-native-core-architecture.md:8` | 2026-09-26 |

Status legend: ✅ Proven · 🟡 Partially proven (qualifier required) · ❌ Not yet / false · UNVERIFIED (not yet checked)
