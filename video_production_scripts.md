# meldra.ai Video Production Scripts & Storyboards

This document contains scene-by-scene script guides, voiceover text, screen actions, and YouTube metadata (descriptions, tags, timestamps) for the three videos featured in the meldra.ai video library.

---

## 🎥 Video 1: What is meldra.ai & the Zero-Copy Lakehouse?
**Duration:** ~8 minutes  
**Objective:** Explain the zero-replication storage model, S3 Apache Iceberg integration, and how serverless DuckDB queries bypass the Spark tax.

### 📝 YouTube Metadata
*   **Title:** What is meldra.ai & the Zero-Copy Lakehouse? (Direct S3 Querying)
*   **Description:** 
    Tired of copying data between legacy databases and proprietary cloud data warehouses? Meet meldra.ai. In this video, we walk through the architecture of a Zero-Copy Lakehouse. Learn how we stream operational data directly to S3 Apache Iceberg and query it serverless using local DuckDB compilation—without moving a single byte of data.
    
    🌐 Website: https://meldra.ai
    🚀 GitHub: https://github.com/SumitAG008/apacheiceberg
    
    Timestamps:
    0:00 - Introduction & The Data Replication Problem
    1:30 - What is a Zero-Copy Lakehouse?
    3:15 - Under the Hood: Apache Iceberg & S3
    4:45 - Live Demo: Chatting with your Lakehouse
    6:30 - Bypassing the Spark Tax
    7:45 - Outro & Next Steps
*   **Tags:** Apache Iceberg, Zero Copy, S3 Lakehouse, Data Engineering, DuckDB, FastAPI, Cloud Data Warehouse, Serverless

---

### 🎬 Scene-by-Scene Storyboard

#### Scene 1: Introduction & The Data Replication Problem (0:00 - 1:30)
*   **Visual:** Show the meldra.ai Landing Page. The cursor hovers over the logo and page features.
*   **Voiceover:** 
    "Welcome! In data engineering, there is a hidden tax that almost every company pays: data replication. Every time you want to query your ERP, sales records, or inventory tables, you are forced to copy it into a proprietary database or cloud warehouse. You're paying for duplicate storage, complex ETL pipelines, and massive cluster compute nodes. That's why we built meldra.ai—a Zero-Copy Lakehouse."

#### Scene 2: What is a Zero-Copy Lakehouse? (1:30 - 3:15)
*   **Visual:** Switch to the **Architecture** tab in the app. Scroll down to the *Meldra Data Flow System* diagram.
*   **Voiceover:** 
    "A zero-copy lakehouse means your data lives in one place—securely in your own S3 bucket—and is queried directly in-place. Meldra links your raw files into open-standard Apache Iceberg tables. No vendor lock-in. No duplicate copies. In this video, we'll see how this lets you run natural language AI queries directly against S3."

#### Scene 3: Under the Hood: Apache Iceberg & S3 (3:15 - 4:45)
*   **Visual:** Go to the **Workspace** tab. Point to the *Active Workspace Details* showing the connected S3 Warehouse URI and the AWS Glue Catalog status.
*   **Voiceover:** 
    "Meldra is built on Apache Iceberg. Iceberg brings ACID transactions, table evolution, and snapshot travel to raw S3 Parquet files. As you see in our Workspace panel, all metadata is managed via the AWS Glue Catalog. Any query engine—whether it's Databricks, Snowflake, or our own engine—can query these exact same files simultaneously without conflicts."

#### Scene 4: Live Demo: Chatting with your Lakehouse (4:45 - 6:30)
*   **Visual:** Switch to the **Chat** tab. Type a query: *"List all tables in my data lake"* and wait for the AI agent to list them. Then type: *"Show me the first 5 rows of sap_bseg"* and watch the table render in the chat.
*   **Voiceover:** 
    "Because our AI agent is grounded in this catalog metadata, you can query your lakehouse in plain English. The agent parses the request, checks the catalog layout, compiles the query, and runs a local DuckDB read. In less than a second, we get a complete table preview directly from S3."

#### Scene 5: Bypassing the Spark Tax (6:30 - 7:45)
*   **Visual:** Switch back to the **Architecture** tab, showing the *"Bypassing the Spark Tax"* article.
*   **Voiceover:** 
    "Databricks and Snowflake require permanent running virtual machines (Spark clusters) just to parse simple queries, costing thousands of dollars in idle fees. Meldra queries Iceberg serverless. When a query is made, we compile the request on-the-fly and execute locally. Compute cost when idle? Exactly zero. In the next video, we'll dive into the specific business use cases we solve for enterprise finance and supply chains."

---

## 🎥 Video 2: Why Zero-Copy? The Business Problems We Solve
**Duration:** ~12 minutes  
**Objective:** Focus on compliance, audit trails, circular loops, and real-time CDC stockout alerts.

### 📝 YouTube Metadata
*   **Title:** Why Zero-Copy? Solve ERP Silos, Spark Costs, & SOX/SOC2 Audit Latency
*   **Description:**
    Enterprise organizations struggle with high operational database fees, disconnected transaction data, and delayed audits. Learn how meldra.ai addresses these challenges:
    - Eliminating circular general ledger transaction loops in real-time.
    - Synchronizing supply chain logs (SAP MM) with stockout alerts.
    - Immutable SOX/SOC2 compliance audit trails on S3.
    
    🌐 Website: https://meldra.ai
    
    Timestamps:
    0:00 - Enterprise Data Bottlenecks
    1:45 - The SAP ERP Data Silo Problem
    3:30 - General Ledger Reconciliation & Fraud Loops
    6:00 - Live Cypher Graph Traversal (Postgres AGE)
    8:30 - Supply Chain CDC Order-to-Cash Lineage
    10:15 - Immutable Audit Trails (SOX & SOC2 Compliance)
    11:30 - Wrap Up
*   **Tags:** Enterprise AI, ERP Integration, SAP Finance, openCypher, Postgres AGE, Compliance, SOC2 Audits, Supply Chain CDC

---

### 🎬 Scene-by-Scene Storyboard

#### Scene 1: Enterprise Data Bottlenecks (0:00 - 1:45)
*   **Visual:** Show the **Learn** tab, highlighting the *Video Library* and *Why Zero-Copy?* card.
*   **Voiceover:** 
    "Enterprises are drowning in data but starving for immediate insights. In this video, we'll look at the real-world business bottlenecks—ERP silos, delayed financial audits, and supply chain stockouts—and show how Meldra resolves them without rewriting your existing databases."

#### Scene 2: The SAP ERP Data Silo Problem (1:45 - 3:30)
*   **Visual:** Go to the **Workspace** tab. Scroll down to *Enterprise ERP Analytics Use Cases* and highlight *SAP General Ledger Matching*.
*   **Voiceover:** 
    "Operational platforms like SAP lock your transaction ledgers inside legacy relational structures. Getting this data out for cross-entity analysis requires nightly export batches, leaving auditing teams looking at stale data. Meldra streams these updates directly to S3 as open Iceberg files, making them queryable instantly."

#### Scene 3: General Ledger Loops & Double-Entry Pathing (3:30 - 6:00)
*   **Visual:** Go to the **Architecture** tab, select the *"Agentic Audits & Loop Reconciliation"* article.
*   **Voiceover:** 
    "Finding circular payment loops or verifying double-entry paths across thousands of general ledger rows is extremely slow using recursive SQL JOINs. That's why Meldra implements a hybrid lake-graph architecture. We map transaction links into a serverless Postgres AGE graph alongside our S3 Iceberg data."

#### Scene 4: Live Cypher Graph Traversal (6:00 - 8:30)
*   **Visual:** Switch to the **Graph** tab. Select the text in the openCypher input window, type: `MATCH (a:Account)-[:TRANSFERS*3..6]->(a) RETURN a.id LIMIT 10`, click **Execute Query**, and show the resulting account list in the table output.
*   **Voiceover:** 
    "Here is our live Cypher console. With one single graph query, our compliance agent traverses multiple hops in milliseconds to locate cyclic transactions where funds flow in a loop. In a standard database, this would take minutes or hours. In Meldra, it's instant."

#### Scene 5: Supply Chain CDC Lineage (8:30 - 10:15)
*   **Visual:** Switch to the **Architecture** tab, showing *"CDC Lineage & Order-to-Cash"* article.
*   **Voiceover:** 
    "In supply chains, a delay in stock replenishment is lost revenue. By using Change Data Capture, Meldra streams inventory modifications as soon as they happen. If inventory falls below safety stocks, the agent automatically executes an API webhook into your ERP's procurement module to draft a purchase order, bypassing manual checks."

#### Scene 6: Immutable Compliance Audits (10:15 - 11:30)
*   **Visual:** Go to the **Audit** tab. Click **Refresh** to show the live execution log.
*   **Voiceover:** 
    "Security is critical. Meldra records every single agent action, query, and tool execution. These logs are written to an append-only Iceberg partition on S3 with snapshot isolation. They are immutable and cryptographically verifiable, ensuring you pass SOX and SOC2 audits with ease."

---

## 🎥 Video 3: Build Your First Pipeline: SAP → Iceberg → AI
**Duration:** ~10 minutes  
**Objective:** Hands-on tutorial showing CSV ingestion, metadata validation, and querying via AI.

### 📝 YouTube Metadata
*   **Title:** Build Your First Zero-Copy Ingestion Pipeline (SAP to S3 Iceberg)
*   **Description:**
    Learn how to build a serverless ingestion pipeline in under 10 minutes.
    In this hands-on tutorial, we:
    1. Upload a CSV containing sample SAP ERP records.
    2. Auto-detect schemas and write Parquet files directly to S3.
    3. Register table definitions in the AWS Glue Catalog.
    4. Query the newly created Iceberg table using natural language AI.
    
    🌐 Website: https://meldra.ai
    📂 Sample Datasets: Available in the Ingest tab of the portal.
    
    Timestamps:
    0:00 - Ingestion Pipeline Overview
    1:15 - Step 1: Connecting your S3 Bucket
    2:45 - Step 2: Uploading Sample CSV
    4:30 - Step 3: Schema Detection & Column Selection
    6:15 - Step 4: Compiling to S3 Parquet
    7:45 - Step 5: Querying with the AI Agent
    9:15 - Verifying the Ingestion via Audit Logs
*   **Tags:** Ingestion Pipeline, ETL Tutorial, S3 Warehouse, CSV to Parquet, DuckDB SQL, AI Database Agent, Glue Catalog, Hands-on Data Engineering

---

### 🎬 Scene-by-Scene Storyboard

#### Scene 1: Ingestion Pipeline Overview (0:00 - 1:15)
*   **Visual:** Show the **Ingest** tab in the main application. Focus on the file drag-and-drop zone.
*   **Voiceover:** 
    "Ready to build your first zero-copy pipeline? In this tutorial, we will take a raw SAP transaction log, write it to S3 as an Apache Iceberg table, register it in our Glue Catalog, and query it using natural language in under 10 minutes."

#### Scene 2: Step 1: Connecting your S3 Bucket (1:15 - 2:45)
*   **Visual:** Point to the sidebar, expand the *Data Lake Config* form. Show the inputs for AWS Region, S3 Warehouse URI, and credentials. Click **Connect Lake** and show the success toast.
*   **Voiceover:** 
    "First, we connect our target data lake. Toggle the data lake connect switch in the sidebar. Enter your AWS region, S3 warehouse URI, and IAM credentials. Once connected, Meldra has permission to write table snapshots directly to S3."

#### Scene 3: Step 2: Uploading Sample CSV (2:45 - 4:30)
*   **Visual:** Hover over the CSV upload drop zone. Click **Select CSV File**, select a sample file (e.g. `employees.csv` or `orders.csv`), and watch the file preview load.
*   **Voiceover:** 
    "Now, we upload our dataset. You can drag and drop your own CSV or click one of our sample buttons. The portal parses the file, displays a preview of the first few rows, and auto-detects the column structures."

#### Scene 4: Step 3: Schema Detection & Column Selection (4:30 - 6:15)
*   **Visual:** Scroll down to show the *Schema Configuration* table. Point to the automatically detected Iceberg column types (e.g., integer, string, double). Enter `finance` as the namespace and `sap_bseg` as the table name.
*   **Voiceover:** 
    "Meldra maps standard data types to Iceberg-compliant schema definitions automatically. Give your table a namespace and a table name—for example, namespace `finance` and table name `sap_bseg`."

#### Scene 5: Step 4: Compiling to S3 Parquet (6:15 - 7:45)
*   **Visual:** Click the **Create Table & Ingest Data** button. The loading overlay appears: *"Writing files to S3... Creating Iceberg metadata snapshots"*. Show the final success toast.
*   **Voiceover:** 
    "Click 'Create Table & Ingest Data'. Meldra compiles the CSV, writes compressed Parquet files to S3, and commits the transaction atomically to the Glue Catalog metadata. The pipeline completes instantly."

#### Scene 6: Step 6: Querying with the AI Agent (7:45 - 9:15)
*   **Visual:** Switch to the **Chat** tab. Type: *"How many rows are in the finance.sap_bseg table?"* and submit. Then ask: *"Show me the top 3 transactions by amount in finance.sap_bseg."*
*   **Voiceover:** 
    "Let's query the table. Switch back to the Chat tab and ask the AI in plain English: 'How many rows are in finance.sap_bseg?' The agent queries S3, retrieves the count, and formats the result. Your raw data is now queryable via AI without any pipeline setup."

#### Scene 7: Outro & Next Steps (9:15 - 10:00)
*   **Visual:** Return to the **Learn** tab and show the *Video Library* again.
*   **Voiceover:** 
    "That's it! You've successfully built a zero-copy operational data pipeline. Explore the other lessons in the Learn tab to understand time travel and schema evolution. Thank you for watching!"
