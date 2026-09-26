# Project Plan & Blueprint — Verifiable Energy Data Platform

**Status:** Living document. This is the single source of truth for what we build, for whom, in what order, and why.
**Created:** 2026-09-25T23:15Z
**Last updated:** 2026-09-26T00:30Z
**Supersedes:** `NOVEMBER_GO_LIVE_ROADMAP.md` (see §11)

### How to use this document
1. **Follow it.** If work isn't on this plan, it waits — or the plan changes first.
2. **Every change gets a Change Log entry (§10)** with a UTC timestamp, what changed, why, and the evidence behind it. No silent edits.
3. **Status is only "done" when a test that can fail proves it** — never from intent (see §8).
4. **Update "Last updated"** at the top whenever anything below changes.

---

## 1. Positioning

**One-line edge:**
> Wherever energy data crosses between parties who don't fully trust each other, and there is no neutral hub, we provide the proof.

**What we sell:** a *receipt* for energy data — independent proof of which readings arrived, which are missing or estimated, and that nothing changed afterwards — which the counterparty can check **without trusting us or the data owner**.

**What we say (and don't say) today:**
- ✅ "Detects post-hoc modifications and sequence gaps."
- ❌ "Tamper-proof" — not until milestone M1 (signature + RFC 3161 verification) is done.
- ✅ "Keep your systems. We add the proof on top." — we sit on top of Kraken / SAP / Itron / in-house systems, never against them.

## 2. Customers

| Order | Who | Why them | Status |
|---|---|---|---|
| **1st (now)** | **Flexibility aggregators & battery/asset operators (UK)** | Paid on delivered volume measured from asset meters they install themselves (P375); new standard baselining rule (Apr 2026); no neutral hub at asset level | Discovery not started |
| 1st (parallel) | **Partners/vendors**: flexibility platforms (e.g. Piclo, Electron, Axle, KrakenFlex), EnergyTag certificate issuers (e.g. Granular Energy, Flexidao), battery/EV/inverter software vendors | They have customers + data; they embed our SDK | Discovery not started |
| 2nd | DNO flexibility / innovation teams | Funded pilots; credibility | Later |
| Year 2 | Large suppliers (E.ON, EDF…), meter-data providers | Need references first | Later |
| Year 2+ | Channel partners: Siemens, Kraken, Itron, Landis+Gyr, SAP | Resell/embed once proven | Later |

**Not first customers:** Siemens (partner, not buyer), Octopus/Kraken (builds in-house), SAP (partners only with customer-proven products), Ofgem/Elexon (regulators — engage only when a rule blocks us).

## 3. Product blueprint

### 3.1 Trust levels — where the proof starts
| Level | Signing point | Proves | When |
|---|---|---|---|
| L3 | At ingestion into our platform | "Unchanged since it reached us" | **Now — pilots** |
| L2 | Agent on site device (battery EMS, EV charger via OCPP, inverter via SunSpec, edge box) | "Unchanged since it left the site" | **Core product — 3–6 months, via device partner** |
| L1 | Inside the meter | "Unchanged since measured" | Years — meter-maker partnership |

Always tell customers which level they are getting.

### 3.2 Architecture
| Layer | Technology | Decision |
|---|---|---|
| **Core proof engine (SDK)** | **C++20** + pybind11 (Python), later Java/C# bindings | Canonical hashing, signatures, nonce/gap detection, Merkle proofs, proof-pack build **and verify**, RFC 3161 check. This is what vendors embed and what runs on edge devices (L2). |
| **Open-source standalone verifier** | Built on the core SDK | Lets any counterparty verify offline without trusting us (milestone M2). |
| Ingestion & API | Python / FastAPI | **Stays Python** — measured 9,254 blocks/s vs ~1,700/s needed for 3M meters. |
| Nonce store | Redis (Lua CAS) | Multi-replica safe. |
| Evidence store | **Apache Iceberg** (append-only evidence tables, snapshot-linked proofs, time travel) | Every proof references an exact Iceberg snapshot. |
| Catalog / access | **Apache Polaris** | Per-tenant, per-market access; works with Spark/Trino/Snowflake/Databricks. |
| Cases & work queue | PostgreSQL (`estate_db`, RLS with non-superuser app role) | Confirmed-gap cases, alerts. |
| Anchoring | **RFC 3161 qualified timestamps** | Legal presumption of accuracy under UK eIDAS. Public-ledger anchoring parked (§9). |
| UI | TypeScript (Vite) | Demo + operations screens; all data fetched live, no browser constants. |

### 3.3 AI capabilities (AI suggests, proofs verify)
1. **Baseline estimation** for flexibility delivery — *first AI feature*.
2. **Gap/anomaly cause classification** (outage vs comms vs meter fault vs possible tampering; feeder/neighbour context).
3. Fraud & gaming detection on delivery reports.
4. Forecasting of expected delivery and gaps.
5. Evidence assistant: plain-English answers with the proof pack attached, from Iceberg snapshots.

### 3.4 Customer experience — prompt-driven operations
**Goal:** a user can type what they want ("prove what site X delivered on 3 March and send it to UKPN") and the platform does it — safely, visibly, with evidence.

**Principles**
1. **Prompt + UI, not prompt instead of UI.** A prompt bar on every screen (command palette); every result opens in a normal screen the user can click through.
2. **Domain tools, not generic ones.** The agent calls product actions: `find_gaps`, `explain_gap`, `estimate_baseline`, `build_proof_pack`, `verify_proof_pack`, `open_case`, `assign_case`, `share_proof_pack`, `delivery_report`. Generic SQL stays available for analysts only.
3. **Read freely, write with confirmation.** Look-ups run immediately. Anything that changes state or leaves the platform (open a dispute, share a pack, change a case) shows a preview and needs one click to confirm.
4. **Every answer carries evidence.** Proof pack, Iceberg snapshot ID and query used are attached — *AI suggests, proofs verify*.
5. **The agent has the user's permissions, never more** (RBAC + tenant scope enforced in every tool).
6. **Everything is audited** — prompt, plan, tool calls, confirmations.
7. **Show progress, fail honestly.** Stream the steps as they happen; if something can't be done, say so — no silent fallbacks.
8. **Measured, not assumed.** An eval set of 30–50 real customer prompts with expected outcomes runs regularly; a drop in score blocks release.

**Example prompts (aggregator segment)**
- "Which sites under-delivered yesterday against baseline, and why?"
- "Build a proof pack for site X, event on 3 March, and share it with UKPN."
- "Show meters with gaps over 2 hours this week, grouped by likely cause."
- "Open a case for every confirmed gap over 5 kWh and assign them to Priya."

**Model & SDK:** Claude via the official Anthropic SDK (tool runner), default `claude-opus-5`; replaces the current LangChain + `claude-sonnet-4-5` setup.

**Sequencing:** the agent is only as good as the real tools and data under it. Domain tools are built as each milestone lands (M1 verify, M3 pipeline/cases); the full prompt-driven experience ships in Phase 3, after M3–M4, so it never runs on mock data.

## 4. Verified status (as of 2026-09-25T23:15Z, commit `45bd880`)

| Area | Status | Evidence |
|---|---|---|
| Verifier rejects forged packs A–D | ✅ Done | Attack script re-run; `test_verifier_rigor.py` in CI, passing |
| Verifier rejects fully fabricated day (pack E, no key/TSA) | ❌ Open → M1 | Returns `VERIFIED` |
| UI "Load Sample Proof Pack" | ❌ Broken | Sample fails: `BLOCK_HASH_MISMATCH` on all 41 readings; 41 not 42 readings |
| CI | ❌ Red (1 test) | Bootstrap-admin promotes first login to Admin (security hole) |
| C++ core (Merkle, route mutator) | ✅ Done, used from Python | CI green incl. ASan/LSan/UBSan |
| C++ GatewayEngine | ⚠️ Built, unused | Python gateway doesn't call it |
| Redis nonce store | ⚠️ Built, not wired to API | — |
| Gateway → writer → Iceberg | ❌ Not wired | `MicroBatchWriter.flush()` is in-memory only |
| Checkpoint → `omission_case` | ❌ Not wired | `init_estate_schema()` never called |
| Alerts | ❌ Not built | — |
| RFC 3161 verification in verifier | ❌ Not built | — |
| Real-data run | ❌ Not started | — |
| Partner/customer conversations | ❌ 0 held | — |
| AI agent (`backend/agent.py`) | ⚠️ Exists, generic | LangChain + `claude-sonnet-4-5`; 10 generic lakehouse tools, no product tools (gaps, proofs, cases); silent "fallback mode" stubs if imports fail; runs LLM-written Python (`distributed_python_extract`) guarded by a blocklist — needs security review |

## 5. Trust-readiness milestones (gate for a partner pilot)

| # | Milestone | Exit criteria (must be provable) | Target |
|---|---|---|---|
| M0 | **Clean base** | CI green; bootstrap-admin fixed; UI sample pack generated live by backend and verified by a CI test | 2026-09-28 |
| M1 | **Cannot be forged** | Verifier checks meter signatures and RFC 3161 token over the anchor; pack E and all attack packs rejected in CI | 2026-10-09 |
| M2 | **Independent verifier** | Open-source CLI verifies a proof pack offline, no network, no account | 2026-10-16 |
| M3 | **Real pipeline** | Ingest → Redis nonce → Iceberg → nightly checkpoint → `omission_case` → proof pack, one end-to-end test | 2026-10-23 |
| M4 | **Real data** | Pipeline run on Low Carbon London (public UK smart-meter data); reproducible gap report | 2026-10-30 |
| M5 | **Security basics** | Non-superuser DB role + RLS test; secrets out of repo; threat model; agent's silent fallback stubs removed; LLM-written-code tool removed from customer-facing agent or sandboxed | 2026-11-06 |
| M6 | **Honest spec** | "What it proves / what it doesn't" (L1/L2/L3) published | 2026-11-06 |

**Pilot-ready = M0–M6 complete.** Discovery conversations start now and do not wait for milestones.

## 6. Roadmap

| Phase | Window | Goal |
|---|---|---|
| 0 | now → 2026-09-28 | M0 |
| 1 | 2026-09-29 → 2026-10-23 | M1–M3 + 4-week discovery test (§7) |
| 2 | 2026-10-26 → 2026-11-13 | M4–M6; first design partner signed |
| 3 | 2026-11 → 2027-03 | UK pilot live; first AI feature (baseline + gap cause); **prompt-driven operations (§3.4) with eval set**; L2 site agent with one device partner |
| 4 | 2027 H2 | UK + one EU market (NL or DE); market rules as configuration |
| 5 | 2028 | USA via FERC Order 2222 aggregators |

## 7. Go-to-market: 4-week discovery test (2026-09-29 → 2026-10-23)
- Talk to **15–20** aggregators, battery operators, flexibility platforms, certificate issuers.
- Core question: *"When a DNO or NESO questions your delivered volume, how do you prove it? What does it cost you?"*
- Also listen for: theft/tampering, flexibility verification, certificate data integrity.
- **Decision rules (fixed in advance):**
  - **Continue** — ≥3 say it's a real, costly problem **and** ≥1 will share data for a pilot.
  - **Refocus** — a different pain repeats; follow it with the same engine.
  - **Stop** — nobody cares.

## 8. Engineering rules
1. **Done = a test that can fail proves it.** No `|| true`, no `if isVisible()` guards.
2. **Never hand-write or AI-generate proof fixtures** — generate them with our own code; CI checks them.
3. **Only quote numbers the CI benchmark prints.**
4. **Scorecards reflect code, not intent.**
5. **Verify summaries before believing them** — run it.
6. **AI actions that change state or leave the platform need user confirmation**, and every AI feature has an eval that can fail.

## 9. Parked (not now, with reason)
| Item | Reason | Revisit when |
|---|---|---|
| Smart contract / public-ledger anchoring | RFC 3161 has legal standing; blockchain hurts UK utility sales; verifier gap was the real risk | A customer/regulator asks; multi-party cross-border settlement |
| Rewriting API/UI/Iceberg layer in C++ | No performance need; C++ Iceberg immature | Never, unless profiling proves otherwise |
| Elexon BSC dispute bundle (`/bsc-pack`) | Elexon's DIP is now the neutral hub for supplier settlement | A supplier customer asks |
| Direct pitch to SAP / Siemens / Kraken | Need customer references first | After 1–2 paying customers |
| Phantom Grid / route-mutation polish, branding polish | Not on the path to a partner pilot | After M6 |

## 10. Change log (newest first)

| Timestamp (UTC) | Change | Rationale | Evidence |
|---|---|---|---|
| 2026-09-26T00:30Z | Added §3.4 prompt-driven customer experience; agent status row; M5 extended (agent fallbacks, LLM-code tool); Phase 3 includes prompt-driven ops; engineering rule 6 | Founder goal: users complete complex tasks by prompt. Existing agent is generic (no product tools), uses an older model via LangChain, and has silent fallbacks — building on it as-is would repeat the "looks like it works" risk | Code review of `backend/agent.py`, `backend/tools.py` |
| 2026-09-25T23:15Z | Created this plan; `NOVEMBER_GO_LIVE_ROADMAP.md` superseded | Old roadmap marked unbuilt work as done and scored 92% readiness; plan needs one honest source of truth with change history | Code review of `main` @ `45bd880` |
| 2026-09-25T23:10Z | Status: UI sample proof pack recorded as broken; rule "never hand-write proof fixtures" added | Sample fails verification on all 41 hashes despite being reported as passing | Sample run through verifier: `BLOCK_HASH_MISMATCH` |
| 2026-09-25T23:00Z | Added milestones M0–M6 as gate for partner pilot | Partner trust requires independently checkable claims | — |
| 2026-09-25T22:00Z | Trust levels L1/L2/L3 adopted; L2 site agent = core product; C++ scope = core SDK + edge agent only | Proof can only start where data is signed; C++ fits embeddable/edge use, not the web layer | Throughput: 9,254/s measured vs ~1,700/s needed |
| 2026-09-25T21:30Z | Global roadmap phases (UK → EU → US via FERC 2222); AI features defined as "AI suggests, proofs verify" | Problem exists wherever there's no neutral hub; focus one market first | — |
| 2026-09-25T21:00Z | Go-to-market shifted to partners/vendors in parallel with direct customers | Founder decision; vendors already hold customers and data | — |
| 2026-09-25T20:00Z | **Lead segment changed: supplier settlement disputes → flexibility & asset-metered delivery** | Elexon's DIP now holds all half-hourly settlement data as neutral hub (weakens supplier dispute pitch); P375 asset meters, Standard Baselining rule (Apr 2026), Elexon Market Facilitator (Dec 2025) create unmet verification need | Elexon, NESO, GOV.UK sources (desk research 2026-09-25) |
| 2026-09-25T19:00Z | Positioning: "Keep your systems, we add the proof"; competitors = status quo, in-house builds, MDM/VEE vendors, Energy Web | Big systems already estimate gaps (VEE); our value is counterparty-verifiable proof, not gap detection | — |
| 2026-09-25T18:00Z | Decision: no pivot away from the core product | Founder decision; customer evidence, not critics, will decide direction | — |
| 2026-09-24T23:00Z | Smart contract / public-ledger anchoring parked | RFC 3161 qualified timestamps have UK legal presumption; verifier didn't check anchors at all | — |
| 2026-09-24T22:00Z | Removed CI masks (`|| true`, `isVisible` guards) | Tests could not fail; exposed 11 hidden failures | CI run #109 |

## 11. Superseded documents
- `NOVEMBER_GO_LIVE_ROADMAP.md` — superseded 2026-09-25T23:15Z. Kept for history only; its readiness scorecard is not accurate.
