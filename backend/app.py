import os
import streamlit as st
from agent import create_iceberg_agent

# ─────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────
st.set_page_config(
    page_title="IcebergGPT – Talk to Your Data Lake",
    page_icon="🧊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ─────────────────────────────────────────
# CUSTOM CSS
# ─────────────────────────────────────────
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }
    
    .main-header {
        background: linear-gradient(135deg, #0f2027, #203a43, #2c5364);
        padding: 2rem 2.5rem;
        border-radius: 16px;
        margin-bottom: 1.5rem;
        box-shadow: 0 8px 32px rgba(0,0,0,0.3);
    }
    
    .main-header h1 {
        color: #56CCF2;
        font-size: 2.2rem;
        font-weight: 700;
        margin: 0;
    }

    .main-header p {
        color: #b0c4d8;
        margin: 0.4rem 0 0 0;
        font-size: 1rem;
    }

    .lesson-card {
        background: linear-gradient(145deg, #1a2a3a, #0f1e2d);
        border: 1px solid #2c4a6e;
        border-left: 4px solid #56CCF2;
        border-radius: 12px;
        padding: 1.2rem 1.5rem;
        margin-bottom: 1rem;
    }

    .lesson-card h4 {
        color: #56CCF2;
        margin: 0 0 0.4rem 0;
    }

    .lesson-card p {
        color: #8ba8c4;
        margin: 0;
        font-size: 0.9rem;
    }

    .prompt-box {
        background: #0d1b2a;
        border: 1px solid #2c4a6e;
        border-radius: 8px;
        padding: 0.8rem 1.2rem;
        font-family: 'Courier New', monospace;
        color: #56CCF2;
        font-size: 0.85rem;
        margin-top: 0.6rem;
    }

    .stat-card {
        background: linear-gradient(145deg, #0f2027, #203a43);
        border: 1px solid #2c4a6e;
        border-radius: 12px;
        padding: 1rem 1.5rem;
        text-align: center;
    }

    .stat-card .number {
        font-size: 2rem;
        font-weight: 700;
        color: #56CCF2;
    }

    .stat-card .label {
        font-size: 0.85rem;
        color: #8ba8c4;
    }

    .badge {
        display: inline-block;
        padding: 0.2rem 0.6rem;
        border-radius: 20px;
        font-size: 0.75rem;
        font-weight: 600;
        margin-right: 0.4rem;
    }

    .badge-blue { background: rgba(86,204,242,0.15); color: #56CCF2; border: 1px solid #56CCF2; }
    .badge-green { background: rgba(39,174,96,0.15); color: #27ae60; border: 1px solid #27ae60; }
    .badge-orange { background: rgba(243,156,18,0.15); color: #f39c12; border: 1px solid #f39c12; }
    
    /* Hide Streamlit Branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🧊 IcebergGPT")
    st.caption("Natural language interface for Apache Iceberg")
    
    st.divider()

    # AWS Config Section
    st.markdown("### ☁️ AWS Configuration")
    st.caption("Connect to your own AWS data lake (BYOC)")

    use_custom_aws = st.toggle("Use my own AWS credentials", value=False)
    
    if use_custom_aws:
        custom_region = st.text_input("AWS Region", placeholder="eu-west-2", key="custom_region")
        custom_s3_uri = st.text_input("S3 Warehouse URI", placeholder="s3://my-bucket/warehouse", key="custom_s3")
        custom_access_key = st.text_input("AWS Access Key ID", type="password", key="custom_access")
        custom_secret_key = st.text_input("AWS Secret Access Key", type="password", key="custom_secret")
        
        if st.button("🔗 Connect to My Data Lake", use_container_width=True):
            if custom_region and custom_s3_uri and custom_access_key and custom_secret_key:
                os.environ["AWS_REGION"] = custom_region
                os.environ["S3_WAREHOUSE_URI"] = custom_s3_uri
                os.environ["AWS_ACCESS_KEY_ID"] = custom_access_key
                os.environ["AWS_SECRET_ACCESS_KEY"] = custom_secret_key
                # Reset agent with new config
                if "agent" in st.session_state:
                    del st.session_state["agent"]
                st.success("✅ Connected to your data lake!")
                st.rerun()
            else:
                st.error("Please fill in all fields.")
    else:
        st.info("📌 Using demo environment. Toggle above to connect your own AWS data lake.")

    st.divider()

    # Quick commands
    st.markdown("### ⚡ Quick Prompts")
    quick_prompts = [
        "List all tables in my data lake",
        "Create a sales table with id, amount, date columns",
        "Show me the first 10 rows of employees",
        "Count all records in a table",
        "Add a column email to employees",
    ]
    for prompt in quick_prompts:
        if st.button(f"▶ {prompt[:35]}...", key=f"qp_{prompt[:10]}", use_container_width=True):
            st.session_state["pending_prompt"] = prompt

    st.divider()
    
    st.markdown("### 📚 Resources")
    st.markdown("- [Apache Iceberg Docs](https://iceberg.apache.org/)")
    st.markdown("- [PyIceberg Docs](https://py.iceberg.apache.org/)")
    st.markdown("- [GitHub Repo](https://github.com/SumitAG008/apacheiceberg)")
    
    st.divider()
    st.caption("Built by Sumit | 🧊 IcebergGPT v1.0")


# ─────────────────────────────────────────
# MAIN CONTENT — TABS
# ─────────────────────────────────────────

st.markdown("""
<div class="main-header">
    <h1>🧊 IcebergGPT</h1>
    <p>Talk to your Apache Iceberg Data Lake in plain English. No SQL expertise needed.</p>
</div>
""", unsafe_allow_html=True)

tab1, tab2, tab3 = st.tabs(["💬 Chat with Your Lake", "📚 Learn Iceberg", "📤 Upload & Ingest"])


# ══════════════════════════════════════════
# TAB 1 — CHAT
# ══════════════════════════════════════════
with tab1:
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown('<div class="stat-card"><div class="number">∞</div><div class="label">Natural Language Queries</div></div>', unsafe_allow_html=True)
    with col2:
        st.markdown('<div class="stat-card"><div class="number">S3</div><div class="label">Serverless Storage</div></div>', unsafe_allow_html=True)
    with col3:
        st.markdown('<div class="stat-card"><div class="number">0</div><div class="label">Spark Clusters Needed</div></div>', unsafe_allow_html=True)
    
    st.markdown("")
    
    if "session_id" not in st.session_state:
        import uuid
        st.session_state.session_id = f"demo_{uuid.uuid4().hex[:8]}"
        
    # Initialize agent
    if "agent" not in st.session_state:
        with st.spinner("Initializing Iceberg agent..."):
            st.session_state.agent = create_iceberg_agent()

    # Chat history
    if "messages" not in st.session_state:
        st.session_state.messages = []
        # Welcome message
        namespace_info = ""
        if not use_custom_aws:
            namespace_info = f"\n\n*Note: You are in a temporary demo workspace. Your isolated namespace is **`{st.session_state.session_id}`**.*"
            
        st.session_state.messages.append({
            "role": "assistant",
            "content": f"""👋 Welcome to **IcebergGPT** — your natural language interface for Apache Iceberg!

I can help you:
- 🗂 **Create tables** with custom schemas in your data lake
- 📥 **Ingest data** from CSV files into Iceberg format on S3
- 🔍 **Query your data** using plain English (powered by DuckDB)
- 🔧 **Manage your lake** — list tables, check schemas, explore metadata{namespace_info}

**Try asking:**
> *"Create a table called orders in namespace {st.session_state.session_id if not use_custom_aws else 'default'} with columns: order_id (integer), customer_name (string), amount (float)"*"""
        })
    
    # Display messages
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"], avatar="🧊" if msg["role"] == "assistant" else "👤"):
            st.markdown(msg["content"])
    
    # Handle quick prompts from sidebar
    if "pending_prompt" in st.session_state:
        user_input = st.session_state.pop("pending_prompt")
    else:
        user_input = st.chat_input("Ask me anything about your Iceberg data lake...")
    
    if user_input:
        st.session_state.messages.append({"role": "user", "content": user_input})
        with st.chat_message("user", avatar="👤"):
            st.markdown(user_input)
        
        with st.chat_message("assistant", avatar="🧊"):
            with st.spinner("🔍 Thinking..."):
                try:
                    response = st.session_state.agent.invoke({"input": user_input})
                    bot_response = response.get('output', '')
                    
                    if isinstance(bot_response, list):
                        parts = []
                        for block in bot_response:
                            if isinstance(block, dict) and "text" in block:
                                parts.append(block["text"])
                            elif hasattr(block, "text"):
                                parts.append(block.text)
                            else:
                                parts.append(str(block))
                        bot_response = "\n".join(parts)
                except Exception as e:
                    bot_response = f"❌ **Error:** {str(e)}\n\n*Tip: Check your AWS credentials and permissions in the sidebar.*"
            
            st.markdown(bot_response)
        
        st.session_state.messages.append({"role": "assistant", "content": bot_response})
    
    if st.button("🗑 Clear Chat", key="clear_chat"):
        st.session_state.messages = []
        st.rerun()


# ══════════════════════════════════════════
# TAB 2 — LEARN ICEBERG (Tutorial Mode)
# ══════════════════════════════════════════
with tab2:
    st.markdown("## 📚 Learn Apache Iceberg — Hands-On Tutorial")
    st.markdown("Learn Iceberg by actually doing it. Each lesson explains a concept and gives you a real prompt to try in the **Chat** tab.")
    
    st.markdown('<span class="badge badge-green">Beginner Friendly</span><span class="badge badge-blue">Hands-On</span><span class="badge badge-orange">Real S3 Writes</span>', unsafe_allow_html=True)
    st.markdown("")

    lessons = [
        {
            "num": "01",
            "title": "What is Apache Iceberg?",
            "icon": "❄️",
            "concept": """Apache Iceberg is an open table format for huge analytics datasets. Think of it as a smarter version of a folder of CSV or Parquet files on S3 — but with ACID transactions, schema evolution, time travel, and partition pruning built in.

**Why does it matter?** Traditional data lakes (S3 folders of Parquet files) have no way to do atomic writes, handle schema changes safely, or query historical versions. Iceberg solves all of this without needing a running Spark or Hive metastore.

**Key components:**
- 📄 **Data files** — Parquet files stored in S3
- 📋 **Metadata files** — JSON files tracking the table schema and snapshots  
- 📑 **Manifest files** — Index of all data files in a snapshot
- 🗂 **Catalog** — Registry of table names → metadata locations (AWS Glue in our case)""",
            "try_prompt": "Tell me what tables currently exist in my default namespace",
            "level": "🟢 Beginner"
        },
        {
            "num": "02",
            "title": "Creating Your First Iceberg Table",
            "icon": "🗂",
            "concept": """In Iceberg, a table is defined by a **schema** (column names + data types) and stored as metadata in your catalog (AWS Glue). The physical data files (Parquet) live in S3.

**Supported column types:**
- `string` — text data
- `integer` / `int` — whole numbers
- `float` / `double` — decimal numbers
- `boolean` — true/false values
- `date` — date values (YYYY-MM-DD)
- `timestamp` — datetime values

**What happens under the hood when you create a table:**
1. PyIceberg sends a `CreateTable` API call to AWS Glue
2. AWS Glue registers the table name and schema
3. A metadata JSON file is written to your S3 bucket
4. The table is now queryable (with 0 rows)""",
            "try_prompt": 'Create a table called "customers" in namespace "default" with columns: customer_id (integer), name (string), email (string), country (string), signup_date (string)',
            "level": "🟢 Beginner"
        },
        {
            "num": "03",
            "title": "Ingesting Data into Your Lake",
            "icon": "📥",
            "concept": """Data ingestion in Iceberg works by **appending Arrow/Parquet batches** to an existing table. Each append creates a new **snapshot** — a point-in-time view of the table.

**What happens during ingestion:**
1. Your CSV is read into a Pandas DataFrame
2. Pandas converts it to an Apache Arrow table
3. PyIceberg writes the Arrow data as a Parquet file to S3 (e.g. `s3://bucket/warehouse/default/customers/data/xxxxx.parquet`)
4. A new snapshot manifest is written to the metadata directory
5. The Glue catalog is updated to point to the latest snapshot

**Key benefit:** If ingestion fails halfway, the old snapshot is untouched. This is ACID-compliant writing to a plain S3 bucket — no Spark, no clusters!

Go to the **Upload & Ingest** tab to try this with a real CSV file.""",
            "try_prompt": "Upload a CSV using the Upload & Ingest tab, then ask me: ingest the uploaded file into the customers table",
            "level": "🟡 Intermediate"
        },
        {
            "num": "04",
            "title": "Querying Your Data Lake with SQL",
            "icon": "🔍",
            "concept": """IcebergGPT uses **DuckDB** to query your Iceberg tables. DuckDB is an in-process SQL engine — think of it as SQLite but for analytical queries on Parquet files.

**How querying works:**
1. DuckDB reads the Iceberg snapshot manifest to find all Parquet files
2. It downloads only the relevant Parquet files from S3 (predicate pushdown)
3. SQL is executed in-memory — results appear in seconds
4. No cluster spin-up, no Spark driver, no EMR costs

**DuckDB supports:**
- `SELECT`, `WHERE`, `GROUP BY`, `HAVING`, `ORDER BY`
- `COUNT`, `SUM`, `AVG`, `MIN`, `MAX`, `DISTINCT`
- `JOIN` between multiple tables
- Window functions (`ROW_NUMBER`, `RANK`, `LEAD`, `LAG`)
- String functions, date functions, and more""",
            "try_prompt": "Show me all records in the customers table, then count customers grouped by country",
            "level": "🟡 Intermediate"
        },
        {
            "num": "05",
            "title": "Schema Evolution — Iceberg's Killer Feature",
            "icon": "🔧",
            "concept": """This is one of the most powerful Iceberg features. In traditional data lakes (raw Parquet on S3), if you add a new column to your data, you must rewrite every existing file. With Iceberg, schema changes are **metadata-only operations** — instant and zero-cost.

**Types of safe schema changes in Iceberg:**
- ✅ **Add a column** — existing data returns NULL for the new column
- ✅ **Rename a column** — metadata update only, no data rewrite
- ✅ **Drop a column** — metadata update, data is hidden not deleted
- ✅ **Widen a type** — e.g. int → long

**What makes this special:**
Traditional databases and Hive tables require costly ETL jobs to evolve schemas. With Iceberg, it is a single API call that updates the metadata JSON file. All existing snapshots remain valid and readable.

This is why Netflix, Apple, LinkedIn, and Airbnb built Iceberg — schema evolution at petabyte scale without downtime.""",
            "try_prompt": 'Add a new column called "phone_number" (string) to the customers table',
            "level": "🔴 Advanced"
        },
        {
            "num": "06",
            "title": "Time Travel — Query Historical Data",
            "icon": "⏰",
            "concept": """Every time you write to an Iceberg table, a new **snapshot** is created. Iceberg keeps a full history of all snapshots, allowing you to query the table as it looked at any point in the past.

**Use cases for time travel:**
- 🐛 Debug data quality issues — *"what did the table look like before that bad ingestion?"*
- 📊 Reproduce reports — *"give me the numbers as of end of last month"*  
- 🔄 Rollback — *"restore the table to yesterday's state"*

**How it works technically:**
Each snapshot has a timestamp and a unique snapshot ID. Iceberg's metadata file contains a snapshot history list. Time travel queries reference a specific snapshot ID or timestamp, and DuckDB/Spark reads the manifest from that snapshot instead of the latest.

**Note:** In our current agent, you can view snapshot metadata. Full time travel SQL (`AS OF TIMESTAMP`) requires Spark or Athena for complex queries.""",
            "try_prompt": "Show me the snapshot history and metadata for the customers table",
            "level": "🔴 Advanced"
        }
    ]
    
    for lesson in lessons:
        with st.expander(f"{lesson['icon']} Lesson {lesson['num']}: {lesson['title']}  —  {lesson['level']}", expanded=False):
            st.markdown(lesson["concept"])
            st.markdown("**💡 Try it now — copy this prompt into the Chat tab:**")
            st.code(lesson["try_prompt"], language=None)
            if st.button(f"▶ Send to Chat", key=f"lesson_{lesson['num']}"):
                st.session_state["pending_prompt"] = lesson["try_prompt"]
                st.info("✅ Prompt loaded! Switch to the 💬 Chat tab to see the result.")


# ══════════════════════════════════════════
# TAB 3 — UPLOAD & INGEST
# ══════════════════════════════════════════
with tab3:
    st.markdown("## 📤 Upload CSV & Ingest into Iceberg")
    st.markdown("Upload a CSV file and let the agent create the table schema and ingest the data into your S3 Iceberg lake automatically.")
    
    col_a, col_b = st.columns([1, 1])
    
    with col_a:
        st.markdown("### 1️⃣ Upload Your CSV")
        uploaded_file = st.file_uploader(
            "Choose a CSV file (max 50MB)",
            type=["csv"],
            key="csv_upload",
            help="Upload any CSV file. The agent will auto-detect the schema and create an Iceberg table for you."
        )
        
        if uploaded_file is not None:
            import pandas as pd
            import tempfile
            import os
            
            df = pd.read_csv(uploaded_file)
            
            st.success(f"✅ File uploaded: **{uploaded_file.name}** ({len(df):,} rows × {len(df.columns)} columns)")
            st.markdown("**Preview:**")
            st.dataframe(df.head(5), use_container_width=True)
            
            # Store in session state for agent use
            with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, prefix='iceberg_upload_') as tmp:
                df.to_csv(tmp.name, index=False)
                st.session_state["uploaded_csv_path"] = tmp.name
                st.session_state["uploaded_csv_name"] = uploaded_file.name
                st.session_state["uploaded_csv_df"] = df
            
            # Auto-detect schema
            type_map = {
                "int64": "integer", "int32": "integer",
                "float64": "double", "float32": "float",
                "bool": "boolean",
                "object": "string",
                "datetime64[ns]": "timestamp"
            }
            schema_preview = []
            for col in df.columns:
                dtype = str(df[col].dtype)
                iceberg_type = type_map.get(dtype, "string")
                schema_preview.append({"Column": col, "Detected Type": iceberg_type})
            
            st.markdown("**Auto-detected Schema:**")
            st.table(pd.DataFrame(schema_preview))
    
    with col_b:
        st.markdown("### 2️⃣ Configure Ingestion")
        
        default_ns = st.session_state.get("session_id", "default") if not use_custom_aws else "default"
        namespace = st.text_input("Namespace", value=default_ns, placeholder="e.g. default, sales", key="ingest_namespace")
        
        suggested_name = ""
        if "uploaded_csv_name" in st.session_state:
            suggested_name = st.session_state["uploaded_csv_name"].replace(".csv", "").replace("-", "_").replace(" ", "_").lower()
        
        table_name = st.text_input("Table Name", value=suggested_name, placeholder="e.g. employees, orders", key="ingest_table")
        
        st.markdown("### 3️⃣ Ingest")
        
        if st.button("🚀 Create Table & Ingest Data", use_container_width=True, type="primary"):
            if "uploaded_csv_path" not in st.session_state:
                st.error("Please upload a CSV file first.")
            elif not table_name:
                st.error("Please enter a table name.")
            else:
                csv_path = st.session_state["uploaded_csv_path"]
                df = st.session_state["uploaded_csv_df"]
                
                # Build the schema JSON string for the agent
                type_map = {
                    "int64": "integer", "int32": "integer",
                    "float64": "double", "float32": "float",
                    "bool": "boolean", "object": "string",
                    "datetime64[ns]": "timestamp"
                }
                schema_cols = []
                for col in df.columns:
                    dtype = str(df[col].dtype)
                    iceberg_type = type_map.get(dtype, "string")
                    schema_cols.append(f'{{\"name\": \"{col}\", \"type\": \"{iceberg_type}\"}}')
                schema_json = "[" + ", ".join(schema_cols) + "]"
                
                prompt = f"""Please do the following two steps in order:
1. Create an Iceberg table named "{namespace}.{table_name}" with this schema: {schema_json}
2. Then ingest data from the CSV file at this path: {csv_path}
   into the table "{namespace}.{table_name}"
Tell me when both steps are complete."""
                
                with st.spinner(f"Creating table **{namespace}.{table_name}** and ingesting {len(df):,} rows..."):
                    try:
                        if "agent" not in st.session_state:
                            st.session_state.agent = create_iceberg_agent()
                        
                        response = st.session_state.agent.invoke({"input": prompt})
                        result = response.get("output", "")
                        
                        if isinstance(result, list):
                            parts = [b.get("text", str(b)) if isinstance(b, dict) else getattr(b, "text", str(b)) for b in result]
                            result = "\n".join(parts)
                        
                        st.success("✅ Ingestion complete!")
                        st.markdown(result)
                        
                        # Add to chat history
                        if "messages" not in st.session_state:
                            st.session_state.messages = []
                        st.session_state.messages.append({"role": "user", "content": f"Ingest {uploaded_file.name} into {namespace}.{table_name}"})
                        st.session_state.messages.append({"role": "assistant", "content": result})
                        
                    except Exception as e:
                        st.error(f"❌ Error during ingestion: {str(e)}")
        
        st.divider()
        st.markdown("### 💡 Sample CSVs to Try")
        
        # Sample CSV generator
        sample_type = st.selectbox("Generate a sample CSV:", [
            "employees (name, department, salary)",
            "orders (product, quantity, price, date)",
            "web_traffic (page, visits, bounces, date)"
        ])
        
        if st.button("📥 Download Sample CSV", use_container_width=True):
            import pandas as pd
            import io
            
            if "employees" in sample_type:
                data = {
                    "emp_id": range(1, 11),
                    "name": ["Alice Smith","Bob Jones","Carol White","David Brown","Eva Green",
                             "Frank Black","Grace Lee","Henry Martin","Iris Wang","Jack Wilson"],
                    "department": ["Engineering","Marketing","Engineering","Sales","HR",
                                   "Engineering","Finance","Marketing","Sales","HR"],
                    "salary": [85000,72000,91000,68000,75000,88000,79000,65000,71000,77000],
                    "hire_date": ["2020-01-15","2019-03-22","2021-06-01","2018-11-30","2022-02-14",
                                  "2020-08-10","2017-05-25","2023-01-08","2021-09-15","2022-07-20"]
                }
            elif "orders" in sample_type:
                data = {
                    "order_id": range(1001, 1011),
                    "product": ["Laptop","Mouse","Keyboard","Monitor","Headset",
                                "Webcam","Desk","Chair","Lamp","Notebook"],
                    "quantity": [1,2,1,1,3,2,1,1,4,10],
                    "price": [999.99,29.99,79.99,399.99,149.99,89.99,299.99,499.99,39.99,4.99],
                    "order_date": ["2024-01-10","2024-01-11","2024-01-11","2024-01-12","2024-01-13",
                                   "2024-01-14","2024-01-14","2024-01-15","2024-01-16","2024-01-16"]
                }
            else:
                data = {
                    "page": ["/home","/about","/products","/contact","/blog",
                             "/pricing","/login","/signup","/docs","/support"],
                    "visits": [4521,1203,3897,876,2341,1654,2987,1432,987,654],
                    "bounces": [1230,432,987,321,765,543,234,567,123,210],
                    "date": ["2024-01-15"] * 10
                }
            
            sample_df = pd.DataFrame(data)
            csv_buffer = io.StringIO()
            sample_df.to_csv(csv_buffer, index=False)
            
            st.download_button(
                "⬇️ Download CSV",
                data=csv_buffer.getvalue(),
                file_name=sample_type.split(" ")[0] + "_sample.csv",
                mime="text/csv",
                use_container_width=True
            )
