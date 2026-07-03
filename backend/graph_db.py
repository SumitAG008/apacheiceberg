import os
import psycopg2
from psycopg2.extras import RealDictCursor
import re
import pandas as pd

def get_db_connection():
    """
    Establishes a connection to the PostgreSQL database housing Apache AGE.
    """
    host = os.environ.get("GRAPH_DB_HOST", "localhost")
    port = os.environ.get("GRAPH_DB_PORT", "5432")
    user = os.environ.get("GRAPH_DB_USER", "postgres")
    password = os.environ.get("GRAPH_DB_PASSWORD", "password123")
    dbname = os.environ.get("GRAPH_DB_NAME", "graphdb")
    
    conn = psycopg2.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        dbname=dbname
    )
    return conn

def init_age_session(conn):
    """
    Initializes the connection session for Apache AGE.
    Must be run on every new connection before executing Cypher.
    """
    with conn.cursor() as cur:
        # Enable extension
        cur.execute("CREATE EXTENSION IF NOT EXISTS age;")
        # Load AGE extension module
        cur.execute("LOAD 'age';")
        # Set search path to include ag_catalog
        cur.execute("SET search_path = ag_catalog, \"$user\", public;")
    conn.commit()

def create_graph_if_not_exists(conn, graph_name: str):
    """
    Creates an Apache AGE graph if it doesn't already exist.
    """
    init_age_session(conn)
    with conn.cursor() as cur:
        # Check if the graph (which maps to a PG schema) already exists in ag_graph catalog
        cur.execute("SELECT count(*) FROM ag_catalog.ag_graph WHERE name = %s;", (graph_name,))
        exists = cur.fetchone()[0] > 0
        
        if not exists:
            cur.execute(f"SELECT create_graph('{graph_name}');")
            conn.commit()
            print(f"Graph '{graph_name}' created successfully.")
        else:
            print(f"Graph '{graph_name}' already exists.")

def sync_dataframe_to_age(graph_name: str, df: pd.DataFrame, source_col: str, target_col: str, edge_label: str = "related_to") -> str:
    """
    Synchronizes nodes and edges from a Pandas DataFrame into Apache AGE.
    """
    conn = None
    try:
        conn = get_db_connection()
        create_graph_if_not_exists(conn, graph_name)
        
        node_count = 0
        edge_count = 0
        
        # We perform the operations in a single transaction
        with conn.cursor() as cur:
            for _, row in df.iterrows():
                src_val = str(row[source_col]).replace("'", "\\'")
                tgt_val = str(row[target_col]).replace("'", "\\'")
                
                # Cypher query to merge nodes and create a directed edge between them
                # In Apache AGE, MERGE is supported. Let's merge both nodes first
                merge_src = f"SELECT * FROM cypher('{graph_name}', $$ MERGE (a:Entity {{id: '{src_val}'}}) RETURN a $$) as (a agtype);"
                cur.execute(merge_src)
                
                merge_tgt = f"SELECT * FROM cypher('{graph_name}', $$ MERGE (b:Entity {{id: '{tgt_val}'}}) RETURN b $$) as (b agtype);"
                cur.execute(merge_tgt)
                
                # Create relationship between the two merged nodes
                create_edge = f"""
                SELECT * FROM cypher('{graph_name}', $$
                    MATCH (a:Entity {{id: '{src_val}'}}), (b:Entity {{id: '{tgt_val}'}})
                    MERGE (a)-[r:{edge_label}]->(b)
                    RETURN r
                $$) as (r agtype);
                """
                cur.execute(create_edge)
                
                node_count += 2
                edge_count += 1
                
        conn.commit()
        return f"Successfully synchronized {len(df)} records to graph '{graph_name}'. Node checkpoints created, edge type: '{edge_label}'."
    except Exception as e:
        if conn:
            conn.rollback()
        return f"Error syncing data to Apache AGE: {str(e)}"
    finally:
        if conn:
            conn.close()

def parse_cypher_return_columns(cypher_query: str) -> list:
    """
    Helper function to parse the RETURN clause of a Cypher query to determine return variables.
    """
    # Regex to find everything after RETURN (case insensitive)
    match = re.search(r'RETURN\s+(.+)$', cypher_query, re.IGNORECASE)
    if not match:
        return ["result"] # default fallback
        
    return_clause = match.group(1).strip()
    # Split by comma but ignore commas inside curly braces or parentheses if any
    parts = [p.strip().split(" ")[-1].split(".")[-1] for p in return_clause.split(",")]
    # Remove any special chars
    clean_parts = [re.sub(r'[^a-zA-Z0-9_]', '', p) for p in parts]
    return [p for p in clean_parts if p]

def execute_cypher_query(graph_name: str, cypher_query: str) -> pd.DataFrame:
    """
    Executes a Cypher query against Apache AGE and returns a Pandas DataFrame.
    """
    conn = get_db_connection()
    try:
        create_graph_if_not_exists(conn, graph_name)
        
        # Parse return columns to construct the SQL "AS (col1 agtype, col2 agtype, ...)" signature
        return_cols = parse_cypher_return_columns(cypher_query)
        if not return_cols:
            return_cols = ["result"]
            
        as_signature = ", ".join([f"{col} agtype" for col in return_cols])
        
        # Construct the final SQL query wrapping the Cypher query
        sql_query = f"SELECT * FROM cypher('{graph_name}', $$ {cypher_query} $$) as ({as_signature});"
        
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql_query)
            rows = cur.fetchall()
            
        # Convert PG rows to a nice DataFrame
        df = pd.DataFrame(rows)
        return df
    except Exception as e:
        raise Exception(f"Failed to execute Cypher query: {str(e)}")
    finally:
        conn.close()

def get_graph_stats(graph_name: str) -> dict:
    """
    Retrieves statistical details about the graph (node count, edge count, label counts).
    """
    conn = None
    try:
        conn = get_db_connection()
        create_graph_if_not_exists(conn, graph_name)
        
        stats = {"nodes": 0, "edges": 0, "labels": []}
        
        # Count nodes
        with conn.cursor() as cur:
            cur.execute(f"SELECT * FROM cypher('{graph_name}', $$ MATCH (n) RETURN count(n) $$) as (c agtype);")
            row = cur.fetchone()
            if row:
                # AGE agtype return is usually a string like "10::numeric" or integer
                stats["nodes"] = int(str(row[0]).split("::")[0].replace('"', '').strip())
                
            # Count edges
            cur.execute(f"SELECT * FROM cypher('{graph_name}', $$ MATCH ()-[r]->() RETURN count(r) $$) as (c agtype);")
            row = cur.fetchone()
            if row:
                stats["edges"] = int(str(row[0]).split("::")[0].replace('"', '').strip())
                
        return stats
    except Exception as e:
        return {"error": str(e), "nodes": 0, "edges": 0}
    finally:
        if conn:
            conn.close()
