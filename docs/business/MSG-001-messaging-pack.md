# MSG-001 — Messaging Pack

**Issued:** 2026-09-06T19:15:00Z  
**Status:** All figures independently verified against commit `0b0478f`

> **Rule for everything below:** every number is measured, not estimated.
> If you add a claim, measure it first. One inflated figure that a
> technical evaluator catches discredits every other figure beside it —
> and your credibility is the only asset you have that competitors can't
> buy.

---

## Verified numbers — use these, nothing else

| Metric | Measured | Conditions |
|---|---|---|
| Verified ingest | **0.108 ms/block** | Single thread, 1,000 blocks, ECDSA P-256 + SHA-256 + nonce CAS |
| Throughput | **9,254 blocks/sec** | Single thread |
| Route validation | **0.007 ms** (142,052/sec) | HMAC-SHA256, constant-time compare |
| Scanner diversion | **0.020 ms** (50,295/sec) | Invalid route → Phantom Grid |
| Headroom, 3M-meter estate | **5.4×** | Against 1,700 blocks/sec sustained |
| Test suite | **28/28 passing** | ETP engine + multi-tenant security regression |

**Derivation of the 1,700/sec figure:** 3,000,000 meters × 48 half-hourly
readings ÷ 86,400 seconds = 1,667 blocks/sec sustained. Say "roughly 1,700"
and be ready to show the arithmetic.

**What you may NOT yet claim:** detection accuracy, false-positive rate,
attacker containment duration, multi-thread or multi-gateway throughput,
anything about real meters. None of it is measured.

---

## The one-sentence version

> A utility can prove a reading was authentic at the meter, and separately
> that a warehouse row hasn't changed. Nothing joins the two — so
> substantiating a settlement figure to a regulator is a manual
> reconciliation taking days. ETP verifies telemetry at the ingestion
> boundary and writes the proof into the lakehouse, so a query returns its
> figure, its snapshot ID and its verification together.

---

## 1. Business audience — CFO, COO, regulatory affairs

**Theme: defensible numbers.** Never mention cryptography.

> When Ofgem or your settlement counterparty challenges a figure, how long
> does substantiating it take, and what do you actually hand them?
>
> Today the answer is a manual reconciliation — pull source readings, match
> them to the aggregate, write a narrative. Days of senior analyst time,
> and what you produce is an argument, not a proof.
>
> ETP changes what you hand over. Every answer comes back with the exact
> data snapshot it was computed from and a cryptographic verification that
> the contributing readings were checked at the gateway and unaltered
> since. Your counterparty can re-run it themselves and get the same
> number. The dispute ends with arithmetic instead of negotiation.

**If asked "is our data insecure today?"** — No. Encryption and
authentication are solved by IEC 62351 and DLMS. What isn't solved is
integrity that survives into the data lake, and what you can prove to a
third party months later.

---

## 2. Industry audience — settlement analysts, network operations

**Theme: your own vocabulary.** These people are won by the schema.

> The tables use `mpan`, `settlement_period`, `feeder_id`, `gsp_group` —
> not generic column names. A settlement analyst reads the schema and
> recognises their own job in it.
>
> Ask a question in plain English. You get the answer, the SQL that
> produced it, the snapshot ID, and the verification status of every
> contributing row. If a reading came in with a broken chain link it's
> flagged `CHAIN_GAP` rather than silently dropped — because a missing
> reading is evidence, not noise.

**Demo line:** *"Watch me change one byte in a stored reading and re-run
the verifier."*

---

## 3. Technical audience — data architects, platform engineers

**Theme: real guarantees, no lock-in.** Be honest about gaps; they've been
lied to before and they can tell.

> Two things worth your attention.
>
> First, RBAC is enforced **below** the query engine. Masking is applied to
> the Arrow data before the relation is registered with DuckDB, so column
> aliasing, subqueries, CTEs and `SELECT *` cannot recover a masked value —
> the value isn't in the relation the engine ever sees. That's a stronger
> property than SQL rewriting, which creative queries defeat.
>
> Second, it's Apache Iceberg on your own object storage. Spark, Trino,
> DuckDB and Dremio can read every byte with us completely out of the
> picture. If we disappear tomorrow your data is untouched and readable.
>
> Known gaps, since you'll find them anyway: SQL `WHERE` predicates aren't
> auto-translated into Iceberg expressions yet, so callers needing file
> pruning must populate `filters` explicitly. The zero-copy Arrow path only
> engages when no RBAC policy applies. Both are in the gap register.

**Volunteering the gaps is the move.** It's what makes the guarantees
credible.

---

## 4. Security audience — CISO, SOC, assurance

**Theme: active defence, and a clean disclosure trail.**

> Existing AMI standards authenticate and encrypt well. Their response to
> detected reconnaissance is to **block** — which tells the attacker
> they've been seen, so they rotate IP and try again. You learn nothing;
> they learn everything.
>
> ETP diverts instead. An invalid route gets a plausible synthetic
> telemetry response from an isolated decoy while the source is flagged.
> The attacker keeps probing a system that isn't real. Diversion costs
> 0.020 ms.
>
> Ingress routes derive from a shared secret and a 60-second epoch window,
> with three windows valid to tolerate clock drift. There is no fixed
> endpoint to scan for.

**Lead with your own findings, don't wait to be asked:**

> We found and fixed two defects in our own gateway. One was an
> availability bug — the nonce counter advanced before signature
> verification, so a single unsigned packet could permanently lock out a
> meter. We exploit-tested it, fixed it, and pinned it with regression
> tests. The write-up is public.

A vendor who can show that is more credible than one claiming a clean
history. Nobody believes the clean history.

---

## 5. AI/ML audience — data scientists, ML engineers

**Theme: bounded execution and verified training data.**

> Two things, and the first is counterintuitive.
>
> The model writes the query. The engine computes the number. It never
> hallucinates a settlement figure because it never produces figures at
> all — DuckDB and Iceberg do. In a regulated context that's the correct
> architecture, not a limitation. "Here's the SQL, here's the snapshot,
> re-run it" is an answer a regulator accepts.
>
> Second: if you're training on grid telemetry, what stops poisoned
> readings entering your training set? ETP verifies every block at the
> ingestion boundary and records the verification state as a first-class
> column. You can filter your training set to verified rows and prove you
> did.

---

## 6. Partner audience — Siemens, AWS, integrators

**Theme: standards alignment and a clean integration seam.**

> The catalogue maps to the IEC Common Information Model — 61970-301 for
> the base model, 61968 for distribution, including part 9 for meter
> reading. A CIM RDF export is implemented and tested.
>
> That matters because CIM is how DMS and EMS vendors already integrate.
> This isn't a proprietary schema you'd have to map to; it speaks the
> model your systems speak.
>
> The interesting gap: CIM models the grid, but has no way to express
> provenance — no standard class for "this reading was verified at ingest,
> here's the proof, here's the anchor." That's a genuine hole in an
> international standard, and it's where the interesting work is.

---

## 7. Investor audience

**Theme: honest asymmetry.**

> The analytics layer is crowded — Databricks with Southern Company's 4.6
> million meters, CGI shipping conversational AMI analytics, Amperon,
> Grid4C, Camus, Pravāh. I'm not competing there and I don't intend to.
>
> Ingestion security is empty. I searched and found nobody doing route
> mutation with active deception at the metering boundary. I have a UK
> patent application filed and a working implementation measured at 9,254
> verified blocks/sec on a single thread.
>
> The customer isn't the utility. It's the analytics vendors who all
> ingest telemetry and none of whom secure it. That's a component sale to a
> technical buyer, not a platform sale into utility procurement — which
> matters, because a sole supplier can't clear a DNO's vendor risk
> assessment and I'm not going to pretend otherwise.

---

## 8. The 60-second demo script

Two terminals side by side. No slides.

| # | Beat | What they see | Say |
|---|---|---|---|
| 1 | Normal ingest | Meters posting, blocks accepted | "Twenty meters, signed readings, all verified." |
| 2 | Route rotates | Active route changes at the window boundary | "The endpoint just moved. Meters follow it — they compute the same value." |
| 3 | **The attack** | Scanner hits the old route, gets a plausible 200. Left terminal shows it flagged and diverted | "He thinks he found the endpoint. He's talking to a decoy. He has no idea." |
| 4 | The tamper | Change one byte, run the verifier, it fails and names the block | "One byte, and we know exactly which reading." |

Beat 3 is the one that sells it. The contrast between what the attacker
sees and what you see is the whole product in ten seconds.

---

## Words to avoid

| Don't say | Say instead | Why |
|---|---|---|
| "Zero-copy architecture" | "Zero-materialisation scan path" | The fast path only engages when no RBAC policy applies |
| "Predicate pushdown" (unqualified) | "Scan pushdown via explicit filters" | SQL `WHERE` isn't auto-translated yet |
| "Blockchain" | "Cryptographically chained, externally anchored" | Procurement resistance, and it isn't one |
| "AI-powered platform" | "Verified data with a natural-language interface" | Leading with AI loses the CISO |
| "Military-grade encryption" | "ECDSA P-256, SHA-256" | The first phrase means nothing |
| "99.7% detection accuracy" | *(nothing — not measured)* | Don't publish figures you haven't run |
| "Real-time verification of the full estate" | "Verified at ingest; spot and batch verification thereafter" | 52 billion rows isn't real-time |

---

## Order of presentation — every audience

1. The regulator problem (provenance gap)
2. What makes the answer different (verified at ingest, carried to rest)
3. The layer they care about
4. The gaps

Never lead with AI. Lead with provable data.
