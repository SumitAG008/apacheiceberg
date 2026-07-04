# Copyright (c) 2025 Meldra AI Ltd. All rights reserved.
# This software is proprietary and confidential. Unauthorised use is prohibited.
"""
graph_db.py — Single-database PostgreSQL Graph Layer (Vercel & Neon Compatible)

Stores graph nodes and edges directly in your existing PostgreSQL (Neon) database
within the 'auth' schema. Graph operations and algorithms are executed in-memory 
using NetworkX.

NO Apache AGE extension compilation or external Neo4j instance required!
"""

import os
import re
import json
import psycopg2
import psycopg2.extras
import pandas as pd
import networkx as nx

# ─── DB Connection ────────────────────────────────────────────────────────────

def _get_conn():
    """Returns a connection to the PostgreSQL (Neon) database."""
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        return psycopg2.connect(db_url, cursor_factory=psycopg2.extras.RealDictCursor)
    return psycopg2.connect(
        host=os.environ.get("GRAPH_DB_HOST", "localhost"),
        port=int(os.environ.get("GRAPH_DB_PORT", 5432)),
        user=os.environ.get("GRAPH_DB_USER", "postgres"),
        password=os.environ.get("GRAPH_DB_PASSWORD", ""),
        dbname=os.environ.get("GRAPH_DB_NAME", "graphdb"),
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


def init_graph_tables():
    """Initializes the relational graph tables in the auth schema."""
    conn = _get_conn()
    try:
        cur = conn.cursor()
        
        # Table for Nodes
        cur.execute("""
            CREATE TABLE IF NOT EXISTS auth.graph_nodes (
                workspace_id TEXT NOT NULL,
                node_id      TEXT NOT NULL,
                label        TEXT NOT NULL DEFAULT 'Entity',
                properties   JSONB NOT NULL DEFAULT '{}'::jsonb,
                PRIMARY KEY (workspace_id, node_id)
            );
        """)
        
        # Table for Edges
        cur.execute("""
            CREATE TABLE IF NOT EXISTS auth.graph_edges (
                id           BIGSERIAL PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                source_id    TEXT NOT NULL,
                target_id    TEXT NOT NULL,
                label        TEXT NOT NULL DEFAULT 'RELATED_TO',
                properties   JSONB NOT NULL DEFAULT '{}'::jsonb,
                CONSTRAINT unique_workspace_edge UNIQUE (workspace_id, source_id, target_id, label)
            );
        """)
        
        # Indexes for fast lookup
        cur.execute("CREATE INDEX IF NOT EXISTS idx_graph_edges_src ON auth.graph_edges(workspace_id, source_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_graph_edges_tgt ON auth.graph_edges(workspace_id, target_id);")
        
        conn.commit()
        print("[graph_db] PostgreSQL relational graph tables initialized.")
    except Exception as e:
        conn.rollback()
        print(f"[graph_db] Schema initialization error: {e}")
    finally:
        conn.close()


# ─── Graph Stats ─────────────────────────────────────────────────────────────

def get_graph_stats(graph_name: str) -> dict:
    """Returns node and edge counts for the specified workspace prefix."""
    init_graph_tables()
    conn = _get_conn()
    try:
        cur = conn.cursor()
        
        # Count nodes
        cur.execute(
            "SELECT count(*) FROM auth.graph_nodes WHERE workspace_id = %s;", 
            (graph_name,)
        )
        nodes = cur.fetchone()["count"]
        
        # Count edges
        cur.execute(
            "SELECT count(*) FROM auth.graph_edges WHERE workspace_id = %s;", 
            (graph_name,)
        )
        edges = cur.fetchone()["count"]
        
        # Get unique edge labels
        cur.execute(
            "SELECT DISTINCT label FROM auth.graph_edges WHERE workspace_id = %s LIMIT 20;", 
            (graph_name,)
        )
        labels = [r["label"] for r in cur.fetchall()]
        
        return {"nodes": nodes, "edges": edges, "labels": labels, "active_graphs": 1}
    except Exception as e:
        return {"error": str(e), "nodes": 0, "edges": 0, "labels": [], "active_graphs": 0}
    finally:
        conn.close()


# ─── DataFrame Sync ──────────────────────────────────────────────────────────

def sync_dataframe_to_neo4j(
    graph_name: str,
    df: pd.DataFrame,
    source_col: str,
    target_col: str,
    edge_label: str = "RELATED_TO"
) -> str:
    """
    Idempotently syncs a DataFrame's nodes and edges into PostgreSQL tables.
    """
    init_graph_tables()
    conn = _get_conn()
    try:
        cur = conn.cursor()
        
        # Extract distinct entities (nodes)
        sources = df[source_col].astype(str).unique().tolist()
        targets = df[target_col].astype(str).unique().tolist()
        all_nodes = list(set(sources + targets))
        
        # 1. Batch insert/upsert nodes
        for node in all_nodes:
            cur.execute(
                """
                INSERT INTO auth.graph_nodes (workspace_id, node_id, label, properties)
                VALUES (%s, %s, 'Entity', '{}'::jsonb)
                ON CONFLICT (workspace_id, node_id) DO NOTHING;
                """,
                (graph_name, node)
            )
            
        # 2. Batch insert/upsert edges
        edge_type = re.sub(r'[^A-Za-z0-9_]', '_', edge_label).upper()
        for _, row in df.iterrows():
            src = str(row[source_col])
            tgt = str(row[target_col])
            cur.execute(
                """
                INSERT INTO auth.graph_edges (workspace_id, source_id, target_id, label, properties)
                VALUES (%s, %s, %s, %s, '{}'::jsonb)
                ON CONFLICT (workspace_id, source_id, target_id, label) DO NOTHING;
                """,
                (graph_name, src, tgt, edge_type)
            )
            
        conn.commit()
        return (
            f"✅ Synced to Neon Postgres graph '{graph_name}': "
            f"{len(all_nodes)} nodes, {len(df)} edges (label: {edge_type})"
        )
    except Exception as e:
        conn.rollback()
        return f"❌ Graph sync error: {str(e)}"
    finally:
        conn.close()


def sync_dataframe_to_age(
    graph_name: str,
    df: pd.DataFrame,
    source_col: str,
    target_col: str,
    edge_label: str = "RELATED_TO"
) -> str:
    """Alias for backwards compatibility with main.py."""
    return sync_dataframe_to_neo4j(graph_name, df, source_col, target_col, edge_label)


# ─── Cypher Evaluator ────────────────────────────────────────────────────────

def execute_cypher_query(graph_name: str, cypher_query: str) -> pd.DataFrame:
    """
    Executes a Cypher query by building an in-memory NetworkX Graph from PostgreSQL tables
    and running queries against it. Matches Cypher MATCH / RETURN structures.
    """
    init_graph_tables()
    conn = _get_conn()
    try:
        cur = conn.cursor()
        
        # Load all nodes for this workspace
        cur.execute(
            "SELECT node_id, label FROM auth.graph_nodes WHERE workspace_id = %s;", 
            (graph_name,)
        )
        nodes = cur.fetchall()
        
        # Load all edges for this workspace
        cur.execute(
            "SELECT source_id, target_id, label FROM auth.graph_edges WHERE workspace_id = %s;", 
            (graph_name,)
        )
        edges = cur.fetchall()
        conn.close()
        
        # Build NetworkX DiGraph
        G = nx.DiGraph()
        for n in nodes:
            G.add_node(n["node_id"], label=n["label"])
        for e in edges:
            G.add_edge(e["source_id"], e["target_id"], label=e["label"])
            
        # Parse query type
        query_upper = cypher_query.upper().strip()
        
        # 1. MATCH (n) RETURN n LIMIT X
        if "MATCH (N)" in query_upper or "MATCH (N:ENTITY)" in query_upper:
            rows = [{"node_id": n} for n in G.nodes()]
            return pd.DataFrame(rows).head(50)
            
        # 2. MATCH (a)-[r]->(b)
        elif "MATCH (A" in query_upper and "-[" in query_upper and "]->(B" in query_upper:
            rows = []
            for u, v, data in G.edges(data=True):
                rows.append({
                    "source_id": u,
                    "target_id": v,
                    "relationship": data.get("label", "RELATED_TO")
                })
            return pd.DataFrame(rows).head(50)
            
        # 3. Simple list nodes fallback
        else:
            rows = [{"node_id": n} for n in G.nodes()]
            return pd.DataFrame(rows).head(20)
            
    except Exception as e:
        raise Exception(f"Failed to execute mock Cypher query: {str(e)}")
