# meldra & ETP Business Case Guide

Who this is for, who it isn't for, real smart grid use cases, and an honest pros/cons list. Written to help prospective utility partners, ISVs, and evaluators decide if this fits.

---

## 1. The One-Line Pitch

meldra is an AI agent for your smart meter Iceberg lakehouse: tell it what you need — verify a settlement figure, check feeder anomalies, investigate topology relationships — and it calls the right tools to do it. Underneath, your smart meter telemetry (AMI) lands once in your cloud storage as open Apache Iceberg — cryptographically verified at the ETP gateway, versioned, and governed — so teams across settlement, grid ops, and compliance work from the same trustworthy tables without vendor lock-in or per-query tax.

---

## 2. Who This Is a Good Fit For

meldra & ETP fit best if most of the following are true for you:

- You manage or ingest high-volume smart meter telemetry (AMI), SCADA logs, or feeder readings (millions to billions of rows).
- You need **provable data provenance** to substantiate settlement figures and tariff calculations to regulators without manual multi-week reconciliations.
- You want the underlying data in an **open format you own** (Apache Iceberg on S3/MinIO), not locked inside a proprietary warehouse format.
- You want **active ingestion security** — Moving Target Defense (MTD) rotating routes and deception honeypots to defend endpoints against scanner reconnaissance.
- Your team includes both technical engineers (who use SQL/Python directly) and non-technical analysts (who query via natural language grounded in catalog metadata).
- You are cost-sensitive: avoiding per-query, per-seat pricing that platforms like Snowflake/Databricks charge once you scale usage to 50B+ rows.

---

## 3. Who This Is NOT a Good Fit For (Yet)

Be honest with prospects about this — it protects the relationship long-term:

- Companies looking for a direct procurement sale to a legacy utility procurement committee **as a sole vendor** without SI or OEM partners (see BC-002 Segment 1–4 strategy).
- Companies needing **live legacy SCADA hardware protocols (e.g., DNP3, IEC 60870-5-104)** on day one without HES integration — those require custom adapter modules.
- A buyer looking for a zero-setup consumer product — someone on your team still needs to configure gateway routes, nonces, and Iceberg table properties.

---

## 4. Real Use Cases (Grounded in Smart Grid & Telemetry)

### A. Verified Telemetry Ingestion (UC-01)
**Problem:** Replay attacks, single-byte tampering, or unverified wire telemetry entering the data lake.
**How ETP helps:** Gateways check monotonic nonces before ECDSA verification ($<1 \text{ ms}$ replay rejection), committing verified blocks to `bronze_ami_readings` with `etp_verify_status = VERIFIED`.
**Good fit if:** you ingest AMI telemetry from millions of edge devices and need wire-to-rest verification guarantees.

### B. Settlement Substantiation & Regulatory Audit (UC-02)
**Problem:** Regulators audit submitted billing/settlement figures; manual reconciliation across raw HES logs takes weeks and costs £50k–£200k.
**How ETP helps:** Execute settlement queries with captured Iceberg Snapshot IDs; verify partition Merkle roots against anchored RFC 3161 TSA checkpoints in seconds.
**Good fit if:** your settlement team spends significant analyst time defending historical billing figures.

### C. Moving Target Defense & Recon Containment (UC-03)
**Problem:** Static ingestion URIs (`/api/v1/telemetry`) attract automated port scanners, DDoS, and credential stuffing. Blocking alerts attackers.
**How ETP helps:** Ingress routes rotate continuously based on clock windows ($W = \lfloor t/60 \rfloor$); invalid-route probes are silently proxied to Phantom Grid honeypots, returning synthetic responses while logging STIX threat intelligence.
**Good fit if:** you operate public-facing ingestion endpoints exposed to scanner traffic.

### D. Grid Event & Feeder Anomaly Investigation (UC-04)
**Problem:** Outages or voltage excursions require fast correlation across thousands of meters to identify probable upstream transformer cause.
**How ETP helps:** Query half-hourly voltage readings, push down partition filters, and traverse Apache AGE topology graphs (`GSP → Substation → Feeder → Meter`) to identify the common upstream asset.
**Good fit if:** grid ops engineers need fast, spatial, and topological root-cause analysis during outages.

---

## 5. Pros and Cons, Stated Plainly

### Pros
- **Patented Ingestion MTD & Deception** — active defense at the boundary rather than passive blocking.
- **No Storage Lock-In** — open Apache Iceberg format on your own S3/MinIO.
- **Built-in Provenance & Governance** — ETP verification status, daily Merkle tree checkpoints, and 7-year retention locks from day one.
- **One Platform, Two Interfaces** — SQL/Python in Query Lab for engineers, Chat for analysts, both calling identical bounded tools.
- **Deterministic & Defensible** — snapshot isolation means queries are reproducible months later.

### Cons — State These Plainly
- **Early-stage product** — expect active development.
- **Merkle Checkpointing requires filing update** — the filed patent spec describes a linear chain; Merkle trees scale verification but require claim updating within the 12-month priority window.
- **Requires SQL-comfortable engineer on team** for initial catalog and policy setup.

---

## 6. Decision Checklist

**Move forward if:**
- [ ] You ingest smart meter (AMI) or grid telemetry requiring scalable, verified storage.
- [ ] You need audit-ready provenance proofs for regulators or settlement counterparties.
- [ ] You want to own your data in open Apache Iceberg format rather than vendor-locked formats.
- [ ] You want active Moving Target Defense at your ingestion boundary.
