# Meldra Data Studio — Enterprise Product Blueprint

From technical toolkit to business platform: personas, use cases, workflows, and roadmap.

---

## 1. What Data Studio Actually Is (In Business Terms)

Data Studio is the control room of the lakehouse. Every enterprise data platform must do five key jobs. Each maps directly to Data Studio modules:

| Job (Business Language) | What it means | Data Studio Module Today |
| :--- | :--- | :--- |
| **Get data in, reliably** | Connect ERP, HR, CRM, and files; land data without unnecessary copies. | Ingest, MCP Gateway, Workspace Connectors |
| **Make data trustworthy** | Validate, deduplicate, standardize, and certify. | Data Quality, Schema Evolution |
| **Never lose history** | Keep every change versioned, reversible, and fully auditable. | Time Travel, Audit Log |
| **Automate the flow** | Scheduled or event-driven pipelines with full execution visibility. | Orchestrator DAG, Triggers & Alerts, Run History |
| **Serve answers safely** | Ensure the right people query the right data at the right cost. | SQL Console, Chat, Graph *(Missing: Semantic Layer, RBAC)* |

> [!NOTE]
> **One-Line Pitch for a CIO:**  
> *"Your SAP, SuccessFactors, and file data lands once in your own S3 as open Apache Iceberg—validated, versioned, and governed. Every team from engineers to finance analysts works from the same certified tables without copies, lock-in, or per-query vendor taxes."*

---

## 2. The Four Personas and Their Capabilities

### 2.1 🛠️ Data Engineer (Daily Driver)
*   **Connect Sources:** S3, SFTP, SuccessFactors, SAP S/4HANA, Salesforce, and flat files with instant test-connection and secure credential vaulting.
*   **Medallion Pipelines:** Build Bronze → Silver → Gold pipelines as code (SQL/Python), run, schedule, and configure auto-retries.
*   **Data-Quality Gates:** Define schemas and contracts that **BLOCK** corrupt loads instead of just logging them.
*   **Monitoring Hub:** Monitor run histories, view per-task runtime logs, and configure failure alerts to Slack/Teams/email.
*   **Lifecycle Ops:** Optimize tables (compaction, snapshot expiry, partition tuning) based on automated policies rather than manual button triggers.

### 2.2 📐 Data Architect (Standards Owner)
*   **Medallion Structure:** Enforce standardized naming structures (namespaces = `bronze`, `silver`, `gold` per business domain).
*   **Schema Governance:** Approve schema changes; destructive actions (drop/rename) require an approval workflow rather than one-click buttons.
*   **Lineage Mapping:** Visualize column-level lineage to trace which source field generated which Gold-tier KPI.
*   **Environment Promotion:** Promote changes through environments (`dev` → `staging` → `prod`) with visual schema diffs and peer sign-offs.
*   **Security & Compliance:** Set retention limits, tag PII data, and apply masking policies at the individual column level.

### 2.3 📊 Business User / Analyst (Growth Audience)
*   **Glossary Catalog:** Search the data catalog in plain business terms (e.g., searching *"vendor spend"* returns `gold_spend_by_region` with description, owner, freshness, and certification badge).
*   **Natural Language Q&A:** Query data using the Chat tab grounded in the catalog (e.g., *"top 10 active vendors by spend in EMEA"* shows the generated SQL but hides complexity).
*   **Analytics Delivery:** Save views, pin personal dashboards, export to Excel/CSV, and subscribe to table updates (*"email me when this refreshes or fails"*).
*   **System Abstraction:** Never exposed to IAM keys, DDL statements, compaction snapshots, or raw logs.

### 2.4 💼 CIO / Data Leader (One Screen, Five Numbers)
*   **Cost:** S3 storage and query compute costs broken down per business domain with trends and forecasting.
*   **Trust:** Platform-wide data-quality trust score and real-time view of top failing contracts.
*   **Compliance:** Live posture audits (GDPR/HIPAA/CCPA) showing PII map, access trails, and retention evidence.
*   **Adoption:** Weekly active users split by persona, self-service ratio, and query counts.
*   **Risk:** Alert dashboard showing stale credentials, unapproved schema drift, and pipelines violating SLA.

---

## 3. Flagship Business Cases & Workflows

### 📂 Business Case A: Vendor Master Consolidation (Procurement)
*   **Problem:** Vendor records are fragmented across SAP, legacy ERPs, and external portals, causing duplicate payments and compliance risks.
*   **Value:** 2–5% procurement savings through deduplication and negotiation leverage; audit-ready master lists.
*   **Workflow:**
    1.  **Ingest:** Load extracts (CSV + S/4HANA OData). Target: `bronze.vendors_raw`. Write Mode: `Append`.
    2.  **Data Quality:** Contracts check for `vendor_id` NOT NULL and valid tax ID structures. Rules log on Bronze but block on Silver.
    3.  **Transformation:** Deduplicate on `vendor_id` keeping the latest timestamp. Standardize country/currency. Output: `silver.vendors_clean`.
    4.  **Orchestrator:** Chain tables to create Gold tables (e.g., spend by region, high-risk vendor alerts).
    5.  **Audit:** Every deployment, edit, and query is logged with actor, timestamp, and run ID for external auditors.

### 💶 Business Case B: SAP Finance Offload (Finance)
*   **Problem:** High-volume accounting tables (`BSEG` / `BKPF`) bloat HANA compute costs and slow down month-end reports.
*   **Value:** Direct reduction in SAP HANA license costs; offloads ad-hoc reporting queries to cheap, fast S3 + DuckDB.
*   **Workflow:**
    1.  **Extraction:** delta-enabled OData extraction pulling daily document changes.
    2.  **Bronze Table:** Raw lines/headers landed on S3, partitioned by fiscal year and period.
    3.  **Data Quality:** Balanced check (Debits == Credits per document) and company code domain checks.
    4.  **Silver Table:** Join headers and lines, resolve GL accounts, and convert currencies using daily rates.
    5.  **Gold Marts:** Generate cost center P&L views, open aging items, and intercompany reconciliation sheets.
    6.  **Time Travel:** Pin month-end close snapshots permanently to document final figures.

### 👥 Business Case C: HR Analytics (SuccessFactors + GDPR)
*   **Problem:** Attrition and compensation reporting are compiled manually, creating GDPR security exposure due to raw PII file exports.
*   **Value:** Complete compliance security via role-based access control (RBAC); historical point-in-time headcount audits.
*   **Workflow:**
    1.  **Connector:** SuccessFactors OData connector fetching `EmpJob` and `EmpCompensation`.
    2.  **PII Masking:** Flag and auto-mask national IDs and bank info in Silver tier; restrict visibility to HR roles.
    3.  **Data Quality:** Enforce `employee_id` uniqueness, FTE bounds ($0.0 \rightarrow 1.0$), and date boundaries.
    4.  **Gold Table:** Monthly attrition models and span-of-control reporting.
    5.  **Retention Policy:** Set automated maintenance jobs to expire metadata and physical snapshots on PII tables per GDPR schedules.

### 🔍 Business Case D: Fraud & Anomaly Detection
*   **Problem:** Fraudulent billing, duplicate payments, or internal invoice collusion go unnoticed in flat relational tables.
*   **Value:** Instant detection of internal bank account manipulation and vendor collusion schemes.
*   **Workflow:**
    1.  **Ingest:** Stream transaction ledgers and vendor registries.
    2.  **Graph Analysis:** Map `vendor ↔ bank-account ↔ address` connections in the Graph tab to highlight vendors sharing bank accounts or physical addresses.
    3.  **Anomaly Engine:** Scheduled alerts flagging newly registered vendors receiving immediate high-value invoices.
    4.  **Alerting:** Push anomalies to verification tables; use Audit logs to track reviewer actions.

---

## 4. Capability Gaps to Build

### 🔴 P0: Trust & Safety (Enterprise Requirements)
*   **RBAC & SSO:** Introduce SAML/OIDC. Add column-level grants and row-level filtering based on user role.
*   **Approval Gateways:** Destructive schema edits or production promotions require dual-approver confirmation.
*   **Secrets Vault:** Encrypt and store API keys, tokens, and DB passwords safely.
*   **Correlated Audit Trails:** Connect every single UI action to a concrete user, timestamp, and transaction ID.

### 🟡 P1: Business-User Layer (Scale Seats)
*   **Data Catalog & Glossary:** Business glossary with certification tags and automated visual lineage.
*   **NL-to-SQL Interface:** Ground the AI chat tab in catalog metadata with SQL preview panels.
*   **Subscriptions:** Scheduled data exports and real-time failure alerts sent directly to email or Slack.
*   **Semantic Layer:** Standardize business definitions (e.g., *"active customer"*) in one place so all SQL Console users calculate identically.

### 🔵 P2: Architect & CIO Control Center
*   **Git-Backed Promotion:** End-to-end promotion pipeline integrated with Git branches.
*   **Cost Analyzer:** Storage trends, forecast calculators, and query compute resource metrics.
*   **Compliance Center:** Automatic PII discovery mapping, audit generation, and snapshot purging.
*   **Policy-Driven Compaction:** Set rules for file size optimize runs instead of manual buttons.

---

## 6. Maturity Roadmap

| Level | Name | What You Have | What You Add | Buyer Proof Point |
| :--- | :--- | :--- | :--- | :--- |
| **L1** | **Working Lakehouse** | Ingest, SQL Console, S3 Iceberg integration, basic schema evolution, Time Travel. | Namespace fix, snapshot-per-write optimization. | *"We connected to S3 and queried 10k vendors in under 10 minutes."* |
| **L2** | **Governed Pipelines** | Orchestrator DAG, DQ rules, Run History, Git status tab. | Blocking DQ gates, alerts integration, two-person schema sign-off. | *"Bad data is blocked from Gold; every transformation pipeline is fully auditable."* |
| **L3** | **Multi-Persona Platform** | Core layout. | SSO/RBAC, Business Glossary, NL-to-SQL catalog-grounded Chat, staging environments. | *"Finance analysts self-serve reports directly from certified tables."* |
| **L4** | **Enterprise Self-Service** | Standard views. | Unified semantic layer, CIO cost/compliance dashboard, connector marketplace. | *"CIO has a single window for lakehouse cost, security, compliance, and user metrics."* |

---

## 7. Design Principles
1.  **Progressive Disclosure:** Tailor navigation based on user role; business analysts see query tools and glossary, engineering tabs stay hidden.
2.  **Audit by Design:** Every single catalog search, query execution, or setting adjustment requires an actor and correlation ID.
3.  **Guardrails over Gates:** Standard configurations should be secure by default (dry-runs enabled, soft deletes, staging constraints), with overrides logged.
4.  **Templates over Empty Consoles:** Pre-built configurations for common ERP integrations (e.g., SAP BSEG, SuccessFactors HR marts) so users don't start with a blank screen.
5.  **Zero Lock-In:** Retain Iceberg format open compatibility on the client's S3 with exportable DAG code.
