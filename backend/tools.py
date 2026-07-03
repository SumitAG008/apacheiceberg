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
from graph_db import sync_dataframe_to_age, execute_cypher_query

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
def run_generic_graph_analysis(namespace: str, table_name: str, source_node_col: str, target_node_col: str, algorithm: str, filter_query: Optional[str] = None) -> str:
    """
    Dynamically build a graph from any Iceberg table and run a graph algorithm.
    
    Args:
        namespace: The namespace of the table.
        table_name: The name of the table.
        source_node_col: The column name to use as the source node for edges.
        target_node_col: The column name to use as the target node for edges.
        algorithm: The algorithm to run ('find_cycles' for fraud, 'degree_centrality' for isolation, 'connected_components' for lineage/clustering).
        filter_query: Optional pandas query string to filter the data before building the graph (e.g. "amount > 9000" or "correction_flag == True").
    """
    try:
        catalog = get_catalog()
        identifier = (namespace, table_name)
        table = catalog.load_table(identifier)
        df = table.scan().to_arrow().to_pandas()
        
        if filter_query:
            try:
                df = df.query(filter_query)
            except Exception as e:
                return f"Error filtering data with query '{filter_query}': {str(e)}"
                
        if df.empty:
            return "No data matches the criteria to build a graph."
            
        import networkx as nx
        from lineage_graph import build_lineage_graph
        
        # Build Nodes
        nodes = []
        all_entities = set(df[source_node_col]).union(set(df[target_node_col]))
        for ent in all_entities:
            nodes.append({"id": ent, "label": str(ent), "color": "blue"})
            
        # Build Edges
        relationships = []
        for _, row in df.iterrows():
            relationships.append((row[source_node_col], row[target_node_col], "related_to"))
            
        G = build_lineage_graph(nodes, relationships)
        
        result_str = f"Graph built successfully with {len(nodes)} nodes and {len(relationships)} edges.\n\n"
        
        # Run Mathematical Algorithm
        if algorithm == "find_cycles":
            cycles = list(nx.simple_cycles(G))
            meaningful_cycles = [c for c in cycles if len(c) > 2]
            if not meaningful_cycles:
                result_str += "Algorithm Output: No cyclical rings detected."
            else:
                result_str += f"Algorithm Output: Detected {len(meaningful_cycles)} cycles (potential rings):\n"
                for i, ring in enumerate(meaningful_cycles):
                    path = " -> ".join([str(x) for x in ring]) + f" -> {ring[0]}"
                    result_str += f"Ring {i+1}: {path}\n"
                    
        elif algorithm == "degree_centrality":
            centrality = nx.degree_centrality(G)
            # Find most isolated (degree 0 or close to 0) in this subgraph
            isolated = sorted(centrality.items(), key=lambda x: x[1])[:5]
            result_str += "Algorithm Output: Most isolated nodes (lowest degree centrality):\n"
            for node, score in isolated:
                result_str += f"- {node}: score {score:.4f}\n"
                
        elif algorithm == "connected_components":
            # Connected components require undirected graph
            undirected_G = G.to_undirected()
            components = list(nx.connected_components(undirected_G))
            result_str += f"Algorithm Output: Found {len(components)} separate connected communities/lineage trees.\n"
            for i, comp in enumerate(components[:5]): # show top 5
                result_str += f"Community {i+1} size: {len(comp)} nodes. Sample: {list(comp)[:3]}\n"
        else:
            result_str += f"Warning: Algorithm '{algorithm}' is not supported. Try 'find_cycles', 'degree_centrality', or 'connected_components'."
            
        return result_str
    except Exception as e:
        return f"Error in graph analysis: {str(e)}"

@tool
def sync_iceberg_to_graph_db(namespace: str, table_name: str, source_node_col: str, target_node_col: str, graph_name: str, edge_label: Optional[str] = "related_to") -> str:
    """
    Synchronizes records from an Iceberg table into a persistent Apache AGE graph.
    
    Args:
        namespace: The namespace of the Iceberg table.
        table_name: The name of the Iceberg table.
        source_node_col: The Iceberg column name representing the source node of relationships.
        target_node_col: The Iceberg column name representing the target node of relationships.
        graph_name: The name of the Apache AGE graph to write to.
        edge_label: Optional label for the relationship (default: 'related_to').
    """
    try:
        catalog = get_catalog()
        identifier = (namespace, table_name)
        table = catalog.load_table(identifier)
        df = table.scan().to_arrow().to_pandas()
        
        if df.empty:
            return "No data in the Iceberg table to synchronize."
            
        if source_node_col not in df.columns or target_node_col not in df.columns:
            return f"Error: Columns {source_node_col} and/or {target_node_col} do not exist in the table."
            
        # Call graph_db helper to sync dataframe to AGE
        result_message = sync_dataframe_to_age(graph_name, df, source_node_col, target_node_col, edge_label)
        return result_message
    except Exception as e:
        return f"Error executing sync: {str(e)}"

@tool
def query_graph_db_cypher(graph_name: str, cypher_query: str) -> str:
    """
    Executes a Cypher query against a persistent Apache AGE graph database and returns tabular results.
    
    Note: Do not wrap the query in SQL; pass the pure Cypher statement.
    Example: "MATCH (a:Entity)-[r]->(b:Entity) RETURN a.id, b.id LIMIT 10"
    
    Args:
        graph_name: The name of the graph to query.
        cypher_query: The pure Cypher query to execute.
    """
    try:
        df = execute_cypher_query(graph_name, cypher_query)
        if df.empty:
            return "Query executed successfully, but returned 0 results."
        return df.to_string()
    except Exception as e:
        return f"Error executing Cypher query: {str(e)}"
