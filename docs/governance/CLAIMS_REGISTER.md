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

Status legend: ✅ Proven · 🟡 Partially proven (qualifier required) · ❌ Not yet / false · UNVERIFIED (not yet checked)
