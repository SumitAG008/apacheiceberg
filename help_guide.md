# meldra Help Guide

Plain-language guide to what meldra is, what everything is called, and how it fits together. Written for someone using the product, not building it.

---

## 1. What meldra is, in one paragraph

meldra is an agentic data platform for Apache Iceberg. At its center is an AI agent that reads what you're trying to do — in plain English — and carries it out by calling the same tools a data engineer would use by hand: ingest a file, run a query, check a relationship in the graph, sync data across tables. Underneath, everything it touches lands in your own cloud storage as Apache Iceberg — validated, versioned, never silently overwritten. You own the storage. Nothing is locked into a vendor's proprietary database, and nothing the agent does is a black box — every step it takes is one of a fixed, visible set of tools.

---

## 2. Speak meldra

| Term you'll see in the app | What it actually means |
|---|---|
| **Apache Iceberg** | The filing format your tables are saved in. Think of it as a smarter version of a spreadsheet folder that remembers every past version of itself and never silently loses data. |
| **Catalog** | The index that knows which tables exist and where their files live. Like a card catalog in a library. |
| **Warehouse** | The actual storage location (an S3 bucket, or a local folder in testing) where your table files physically sit. |
| **Namespace** | A folder for grouping related tables — e.g. `default`, `finance`, `hr`. |
| **Bronze / Silver / Gold** | A common way of organizing data by how "clean" it is. Bronze = raw, as-loaded. Silver = cleaned and deduplicated. Gold = ready for business reporting/dashboards. |
| **Snapshot / Time Travel** | Every change to a table is saved as a snapshot. Time Travel lets you look at (or restore) the table exactly as it was at an earlier point — useful for "what did this look like before the bad import last Tuesday." |
| **Schema Evolution** | Adding, removing, or renaming a column in a table without having to rebuild the whole table from scratch. |
| **Data Contract** | A rule you set on a table — e.g. "this column can never be empty" or "this number must be between 0 and 1." Contracts can be set to block bad data from loading at all. |
| **Ingestion / Ingest** | Loading data in, from a CSV file or a connected system like SuccessFactors. |
| **Write Mode: Append / Overwrite / Upsert** | Append = add new rows. Overwrite = replace everything. Upsert = update existing rows and add new ones, matched on a key column (e.g. `vendor_id`). |
| **RBAC (Role-Based Access Control)** | Rules about who can see what. E.g. a Business Analyst role might see a vendor table but with the bank account column blanked out; an Admin sees everything. |
| **Column Masking** | Hiding or redacting a specific column's real values for certain roles, instead of hiding the whole table. |
| **Query Lab / DQE (Distributed Query Engine)** | The tab where you write SQL directly, or run a small Python script, or explore graph connections, against your tables — the same tools the Agent reaches for, just driven by you instead of a plain-English request. |
| **DuckDB** | The engine that actually runs your SQL queries fast, without needing a separate database server. |
| **The meldra Agent** | An AI agent (built on Claude) with a fixed toolbox: create a table, ingest a CSV, run a SQL query, analyze a graph, sync data to the graph store, query the graph store. You ask it something in plain English ("top 10 vendors by spend in EMEA"); it decides which tool(s) to call, in what order, runs them, and can use the result of one step to decide the next — that decision loop is what makes it "agentic" rather than a single fixed lookup. |
| **Tool-calling** | How the Agent actually *does* things instead of just talking. Each capability (query a table, ingest a file, etc.) is exposed to the Agent as a discrete, named action it can invoke with specific arguments — the same action you'd trigger by hand in Query Lab, just requested in plain English instead of clicked. |
| **Agent Loop** | The cycle the Agent runs per request: read what you asked → decide whether a tool is needed → call it → look at the result → decide the next step or give you a final answer. It's capped at a fixed number of steps, so it can't run away indefinitely. |
| **Graph tab** | A view of your data as connections rather than rows and columns — e.g. which vendors share a bank account, useful for spotting fraud rings or tracing lineage. |
| **Audit Log** | A record of every significant action taken in the platform — who did what, when, including every tool call the Agent makes on your behalf — for compliance and troubleshooting. |
| **Maintenance: Optimize / Expire Snapshots** | Housekeeping tasks. Optimize compacts small files into bigger ones for faster queries. Expire Snapshots deletes old version history you no longer need, to save storage cost. |

---

## 3. How data actually flows through the platform

```
Source data (CSV, SuccessFactors export, etc.)
        │
        ▼
  Ingest tab  ──── Data Contracts check here (can block bad data)
        │
        ▼
  Bronze table (raw, as loaded, on your S3)
        │
        ▼
  Silver table (cleaned, deduplicated — you build this via SQL/Query Lab)
        │
        ▼
  Gold table (business-ready — dashboards, reporting)
        │
        ▼
  Query Lab / Agent / Graph ── this is how people (and the Agent, on your behalf) reach the data
        │
        ▼
  Everything above is logged to the Audit tab, tool calls included
```

---

## 4. Who uses which tab (the four personas)

| Persona | What they mainly do |
|---|---|
| **Data Engineer** | Connects sources, builds Bronze → Silver → Gold pipelines, sets Data Contracts, monitors ingestion runs. |
| **Data Architect** | Approves schema changes, sets naming standards, manages retention and PII masking rules. |
| **Business Analyst** | Searches the catalog in plain terms, asks the Agent questions, views dashboards. Never touches raw credentials or DDL. |
| **Admin** | Everything above, plus user roles, RBAC policy configuration, and destructive actions (dropping tables/namespaces). |

---

## 5. What's live today vs. what's roadmap

Being upfront about this matters more than it might seem — treat this table as the current source of truth, not the marketing copy.

| Feature | Status |
|---|---|
| Iceberg ingestion (CSV, SuccessFactors OData) | **Live** |
| Data Quality Contracts (blocking bad loads) | **Live** |
| Time Travel / snapshots | **Live** |
| Query Lab — SQL mode | **Live** |
| Query Lab — Python extraction scripts | **Live** (sandboxed, Admin/Data Engineer only) |
| Column-level RBAC masking | **Live** |
| The meldra Agent (plain-English, tool-calling) | **Live** (works, but doesn't yet enforce the same column masking as Query Lab in every path — ask before relying on it for sensitive columns) |
| Audit log | **Live** |
| Graph tab — storing/viewing connections | **Live** |
| Graph tab — full Cypher query language | **Roadmap** (currently a simplified pattern-matcher, not the real thing) |
| MCP Gateway (SAP BAPI, Snowflake, Fraud/IAM automation) | **Demo/illustrative only** — these currently return example responses to show what the workflow will look like, not live connections to a real SAP or Snowflake system |
| Single Sign-On (SSO) | **Roadmap** |
| Multi-tenant SaaS isolation | **In progress** |

---

## 6. Getting started (first 10 minutes)

1. Register an account (first account on a fresh instance becomes Admin automatically).
2. Verify your email with the code sent to you.
3. Go to **Ingest**, upload one of the sample CSVs (or your own), review the auto-detected schema, and load it.
4. Go to **Query Lab**, run a `SELECT * FROM iceberg_table LIMIT 10` against the table you just created.
5. Go to the **Agent** and ask a plain-English question about the same table — watch it choose a tool and run it.
6. Go to **Audit** and see that both actions above were logged, including the Agent's tool call.
