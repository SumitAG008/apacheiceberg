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
        
        # Execute query using duckdb
        # DuckDB automatically finds the local variable `iceberg_table`
        result = con.execute(sql_query).fetchdf()
        
        # Convert result to string/JSON representation for the agent
        return result.to_string()
    except Exception as e:
        return f"Error executing query: {str(e)}"
