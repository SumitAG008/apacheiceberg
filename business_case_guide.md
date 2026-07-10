# meldra Business Case Guide

Who this is for, who it isn't for, real use cases, and an honest pros/cons list. Written to help a prospective user or buyer decide if this fits, not to oversell it.

---

## 1. The one-line pitch

meldra is an AI agent for your Iceberg lakehouse: tell it what you need — ingest a file, check a number, investigate a relationship — and it calls the right tools to do it. Underneath, your SAP, SuccessFactors, and file data lands once in your own cloud storage as open Apache Iceberg — validated, versioned, and governed — so people across the company can work from the same trustworthy tables without copies, vendor lock-in, or per-query fees from a big-name platform.

---

## 2. Who this is a good fit for

meldra fits best if most of the following are true for you:

- You have data scattered across SAP, SuccessFactors, Salesforce, or plain CSV/Excel exports, and no single place it all lands.
- You don't have (or don't want to hire) a dedicated data engineering team just to stand up a governed data lake.
- You want the underlying data in an **open format you own** (Apache Iceberg on your own S3), not locked inside a vendor's proprietary storage.
- You need **some** governance — audit trails, column-level masking for sensitive fields, contracts that block bad data — but not a full enterprise compliance program on day one.
- Your team includes both technical people (who'll use SQL/Python in Query Lab directly) and non-technical people (who'd rather just tell the Agent what they need in plain English).
- You're cost-sensitive: you want to avoid the per-query, per-seat pricing that platforms like Snowflake/Databricks charge once you scale usage.

## 3. Who this is NOT a good fit for (yet)

Be honest with prospects about this — it protects the relationship long-term:

- Companies needing **petabyte-scale distributed compute** across thousands of concurrent users — this is not there yet.
- Companies that require **live, certified integrations** with SAP RFC/BAPI, Snowflake, or automated IAM/fraud systems **today** — those are currently illustrative demo flows, not working connections.
- Companies that need **SSO, SOC2/HIPAA-certified compliance, or full multi-tenant isolation** as a signed contractual requirement right now.
- A buyer looking for a fully non-technical, zero-setup product — someone on your team still needs to be comfortable enough to configure ingestion and RBAC policies.

---

## 4. Real use cases (grounded in what the product actually does today)

### A. Vendor Master Consolidation (Procurement)
**Problem:** Vendor records duplicated across SAP, legacy ERPs, and portals cause duplicate payments and compliance risk.
**How meldra helps:** Load vendor extracts (CSV or SAP OData-style feeds) into Bronze, apply a Data Contract requiring `vendor_id` and a valid tax ID, deduplicate in Silver keeping the latest record per vendor, then build a Gold "spend by region" table analysts query directly.
**Good fit if:** you have vendor data in 2+ systems and no single deduplicated source of truth today.

### B. SAP Reporting Offload (Finance)
**Problem:** Heavy reporting queries against live SAP tables slow down the system everyone else uses for actual transactions.
**How meldra helps:** Pull a copy of the reporting-relevant tables into Iceberg via CSV/OData export, run reporting queries against DuckDB/Query Lab instead of hitting SAP directly, use Time Travel to permanently pin month-end snapshots.
**Good fit if:** your finance team's ad-hoc reporting is currently competing with production SAP transactions for compute.

### C. HR Analytics (SuccessFactors)
**Problem:** Attrition/compensation reporting is compiled manually, with raw PII (national IDs, salaries) exported into spreadsheets that get emailed around.
**How meldra helps:** Connect the real SuccessFactors OData connector, mask national ID/bank fields for non-HR roles via column-level RBAC, enforce `employee_id` uniqueness via Data Contracts.
**Good fit if:** you already have SuccessFactors and are currently doing this reporting via spreadsheet exports.

### D. Vendor/Transaction Relationship Analysis
**Problem:** Fraud or collusion patterns (shared bank accounts, unusual new-vendor payment velocity) aren't visible in flat tables.
**How meldra helps:** The Graph tab visualizes vendor-to-bank-account-to-address relationships from your existing tables. *(Note: today this covers connection storage and visualization; more advanced Cypher-style querying is on the roadmap — see the Help Guide's status table.)*
**Good fit if:** you want an exploratory first look at these relationships now, understanding the query language itself is still basic.

---

## 5. Pros and cons, stated plainly

### Pros
- **A real reasoning agent, not a search bar** — the meldra Agent chains tool calls (ingest → query → analyze) to get you an answer, instead of one canned lookup at a time.
- **No storage lock-in** — your data lives in Apache Iceberg on your own S3, readable by any Iceberg-compatible tool, not trapped in a proprietary format.
- **Governance is built in, not bolted on** — audit logging, data contracts, and RBAC masking exist from day one rather than being a paid add-on.
- **One platform, two ways in** — SQL/Python in Query Lab for engineers who want direct control, the Agent in plain English for everyone else, both calling the same underlying tools.
- **Time Travel by default** — every write is a recoverable snapshot, not a silent overwrite.
- **Meaningfully cheaper** for teams who don't need Databricks/Snowflake-scale compute.

### Cons — say these out loud before someone finds them the hard way
- **Young product.** Expect rough edges; this is not a decade-mature platform.
- **The Agent doesn't yet enforce the same column masking as Query Lab in every path** — don't rely on it for sensitive columns until that's closed.
- **Single environment today.** True multi-tenant SaaS isolation is in progress, not finished — currently best suited to one deployment per customer rather than shared self-serve signup.
- **Some integrations are illustrative, not live.** The SAP BAPI/Snowflake/Fraud automation tools currently demonstrate the intended workflow with example data; they are not yet connected to a real SAP or Snowflake system.
- **The graph query language is a simplified subset today**, not full Cypher.
- **No SSO yet** — access is email/password + email OTP MFA.
- **Requires a comfortable-with-SQL person on the team** for full value, even though the Agent lowers that bar for everyday questions.

---

## 6. Decision checklist

**Move forward if:**
- [ ] You have data scattered across 2+ source systems with no unified, governed landing zone.
- [ ] You want to own your data in an open format rather than a vendor's proprietary store.
- [ ] You can tolerate "early-stage product" rough edges in exchange for cost and simplicity.
- [ ] You have at least one person on the team comfortable configuring ingestion/RBAC.

**Wait, or look elsewhere for now, if:**
- [ ] You have a hard contractual requirement for SSO, certified compliance, or live SAP/Snowflake integration on day one.
- [ ] You need multiple customer organizations securely isolated on one shared instance today.
- [ ] You need proven scale at petabyte/thousands-of-concurrent-users level.
