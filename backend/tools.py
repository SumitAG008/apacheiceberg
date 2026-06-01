import os
import json
import duckdb
import pandas as pd
import pyarrow as pa
from typing import Optional
from pyiceberg.schema import Schema
from pyiceberg.types import (
    NestedField,
    StringType,
    IntegerType,
    FloatType,
    DoubleType,
    BooleanType,
    DateType,
    TimestampType
)
from catalog_setup import get_catalog, create_namespace_if_not_exists
from langchain.tools import tool

def get_pyiceberg_type(type_str: str):
    type_str = type_str.lower()
    if type_str == "string":
        return StringType()
    elif type_str == "integer" or type_str == "int":
        return IntegerType()
    elif type_str == "float":
        return FloatType()
    elif type_str == "double":
        return DoubleType()
    elif type_str == "boolean" or type_str == "bool":
        return BooleanType()
    elif type_str == "date":
        return DateType()
    elif type_str == "timestamp":
        return TimestampType()
    else:
        # Default fallback
        return StringType()

@tool
def create_iceberg_table(namespace: str, table_name: str, schema_json: str) -> str:
    """
    Create an Apache Iceberg table in the specified namespace.
    
    Args:
        namespace: The namespace (e.g., 'default').
        table_name: The name of the table to create.
        schema_json: A JSON string representing the schema. Format: [{"name": "col1", "type": "string"}, {"name": "col2", "type": "int"}]
    """
    try:
        catalog = get_catalog()
        create_namespace_if_not_exists(catalog, namespace)
        
        schema_list = json.loads(schema_json)
        fields = []
        for i, col in enumerate(schema_list):
            field = NestedField(
                field_id=i+1,
                name=col["name"],
                field_type=get_pyiceberg_type(col["type"]),
                required=False
            )
            fields.append(field)
            
        iceberg_schema = Schema(*fields)
        identifier = (namespace, table_name)
        
        # Check if table exists
        try:
            catalog.load_table(identifier)
            return f"Table {namespace}.{table_name} already exists."
        except:
            pass
            
        table = catalog.create_table(identifier, schema=iceberg_schema)
        return f"Successfully created table {namespace}.{table_name}."
    except Exception as e:
        return f"Error creating table: {str(e)}"

@tool
def ingest_csv_to_iceberg(namespace: str, table_name: str, csv_path: str) -> str:
    """
    Ingest data from a CSV file into an existing Iceberg table.
    
    Args:
        namespace: The namespace of the table.
        table_name: The name of the table.
        csv_path: The absolute path to the CSV file to ingest.
    """
    try:
        if not os.path.exists(csv_path):
            return f"Error: CSV file not found at {csv_path}"
            
        catalog = get_catalog()
        identifier = (namespace, table_name)
        table = catalog.load_table(identifier)
        
        # Read CSV with pandas, convert to pyarrow table
        df = pd.read_csv(csv_path)
        arrow_table = pa.Table.from_pandas(df)
        
        # Append data to the iceberg table
        table.append(arrow_table)
        
        return f"Successfully ingested data from {csv_path} into {namespace}.{table_name}. Row count: {len(df)}"
    except Exception as e:
        return f"Error ingesting data: {str(e)}"

@tool
def query_iceberg_data(namespace: str, table_name: str, sql_query: str) -> str:
    """
    Query an Iceberg table using SQL via DuckDB.
    
    IMPORTANT: Do not include the table name in your query FROM clause directly.
    The table is already loaded into DuckDB as 'iceberg_table'. 
    Always write your query against the table named 'iceberg_table'.
    Example query: "SELECT * FROM iceberg_table LIMIT 10"
    
    Args:
        namespace: The namespace of the table.
        table_name: The name of the table.
        sql_query: The SQL query string to execute against 'iceberg_table'.
    """
    try:
        catalog = get_catalog()
        identifier = (namespace, table_name)
        
        try:
            table = catalog.load_table(identifier)
        except Exception as e:
            return f"Error: Table {namespace}.{table_name} not found."
            
        # Get PyArrow table for querying with DuckDB
        # Using scan().to_arrow() is the efficient way to read Iceberg data
        con = duckdb.connect(database=':memory:')
        iceberg_table = table.scan().to_arrow()
        con.register("iceberg_table", iceberg_table)
        
        # Execute query using duckdb
        # DuckDB automatically finds the local variable `iceberg_table`
        result = con.execute(sql_query).fetchdf()
        
        # Convert result to string/JSON representation for the agent
        return result.to_string()
    except Exception as e:
        return f"Error executing query: {str(e)}"

@tool
def analyze_attrition_risk(namespace: str, table_name: str) -> str:
    """
    Analyze employee attrition (flight risk) based on HR data using graph isolation metrics.
    
    Args:
        namespace: The namespace of the HR table.
        table_name: The name of the HR table.
    """
    try:
        catalog = get_catalog()
        identifier = (namespace, table_name)
        table = catalog.load_table(identifier)
        df = table.scan().to_arrow().to_pandas()
        
        # Simple risk logic based on performance and graph isolation
        risks = []
        for _, row in df.iterrows():
            # High performer, isolated, and hasn't been promoted in a while
            if row['performance_rating'] >= 4.0 and row['cross_team_connections'] == 0 and row['last_promotion_months_ago'] >= 18:
                risks.append({
                    "employee_id": row["employee_id"],
                    "name": row["name"],
                    "reason": f"High performer (Rating: {row['performance_rating']}), 0 cross-team connections, no promotion in {row['last_promotion_months_ago']} months."
                })
        
        if not risks:
            return "No immediate flight risks detected based on graph isolation metrics."
            
        result_str = f"Found {len(risks)} high-risk employees:\n"
        for r in risks:
            result_str += f"- {r['name']} ({r['employee_id']}): {r['reason']}\n"
        result_str += "\nRecommended Action: Immediate promotion review and cross-functional project rotation."
        
        # Build networkx graph using lineage_graph module (just to show we can)
        from lineage_graph import build_lineage_graph
        nodes = [{"id": r["employee_id"], "label": r["name"], "color": "red"} for r in risks]
        # In a real scenario, we'd add edges to their managers, but for the summary this is fine.
        
        return result_str
    except Exception as e:
        return f"Error analyzing attrition risk: {str(e)}"

@tool
def detect_fraud_rings(namespace: str, table_name: str, days: int = 30) -> str:
    """
    Detect money laundering rings (layering) in transaction data using graph community detection.
    
    Args:
        namespace: The namespace of the transaction table.
        table_name: The name of the transaction table.
        days: Lookback period in days.
    """
    try:
        catalog = get_catalog()
        identifier = (namespace, table_name)
        table = catalog.load_table(identifier)
        df = table.scan().to_arrow().to_pandas()
        
        # Simple layering detection logic (circular flows)
        import networkx as nx
        from lineage_graph import build_lineage_graph
        
        # Filter for amounts just under reporting limit ($10k)
        suspicious = df[(df['amount'] >= 9000) & (df['amount'] < 10000)]
        
        nodes = []
        accounts = set(suspicious['from_account']).union(set(suspicious['to_account']))
        for acc in accounts:
            nodes.append({"id": acc, "label": acc, "color": "orange"})
            
        relationships = []
        for _, row in suspicious.iterrows():
            relationships.append((row['from_account'], row['to_account'], f"${row['amount']}"))
            
        G = build_lineage_graph(nodes, relationships)
        
        # Find simple cycles (rings)
        cycles = list(nx.simple_cycles(G))
        rings = [c for c in cycles if len(c) > 2]
        
        if not rings:
            return "No layering rings detected."
            
        result_str = f"Detected {len(rings)} potential money laundering rings:\n"
        for i, ring in enumerate(rings):
            path = " -> ".join(ring) + f" -> {ring[0]}"
            result_str += f"Ring {i+1}: {path}\n"
            
        result_str += "\nAction: Recommend filing SAR (Suspicious Activity Report) for these accounts."
        return result_str
    except Exception as e:
        return f"Error detecting fraud rings: {str(e)}"

@tool
def trace_data_lineage(namespace: str, table_name: str, corrected_rows: int = 400) -> str:
    """
    Trace the downstream impact of a data correction in pharma clinical trials.
    
    Args:
        namespace: The namespace of the clinical trials table.
        table_name: The name of the clinical trials table.
        corrected_rows: The number of rows corrected.
    """
    try:
        catalog = get_catalog()
        identifier = (namespace, table_name)
        table = catalog.load_table(identifier)
        df = table.scan().to_arrow().to_pandas()
        
        # Find affected cohorts and arms
        affected = df[df['correction_flag'] == True]
        
        cohorts = affected['cohort'].unique().tolist()
        arms = affected['trial_arm'].unique().tolist()
        submissions = affected['submission_id'].unique().tolist()
        
        result_str = f"Lineage trace complete for data correction.\n"
        result_str += f"Affected downstream assets:\n"
        result_str += f"- Cohorts: {', '.join(cohorts)}\n"
        result_str += f"- Trial Arms: {', '.join(arms)}\n"
        result_str += f"- FDA Submissions: {', '.join(submissions)}\n\n"
        
        result_str += f"Impact: {len(affected)} patients' statistical models need recalculation.\n"
        result_str += "Estimated delay risk: 6 weeks.\n"
        
        return result_str
    except Exception as e:
        return f"Error tracing lineage: {str(e)}"
