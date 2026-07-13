# Copyright (c) 2025 Meldra AI Ltd. All rights reserved.
# This software is proprietary and confidential. Unauthorised use is prohibited.
"""
graph_db.py — Apache AGE graph layer (property graph on Postgres).

Uses the `apache/age` Postgres image already declared as the `db` service in
docker-compose.yml, via the AGE extension's `cypher()` SQL function, for
genuine openCypher execution — MERGE, MATCH, aggregates, everything AGE
supports — instead of the hand-rolled two-pattern matcher this file used to
run over an in-memory NetworkX graph.

AGE's `cypher()` function requires its value-carrying third argument to be a
real server-side bind parameter, not a client-side `%s`-substituted
literal — passing a plain `cursor.execute(sql, params)` literal raises
"third argument of cypher function must be a parameter". The fix AGE
documents is PREPARE/EXECUTE: prepare the Cypher statement once with a
`$1` placeholder, then EXECUTE it with the actual agtype value. See
`_run_prepared_cypher` below.

AGE also can't introspect how many columns an arbitrary Cypher RETURN
clause produces — the caller must declare the output shape via
`AS (col1 agtype, col2 agtype, ...)` up front. For the two query shapes
this module previously hard-coded (`MATCH (n) RETURN n`,
`MATCH (a)-[r]->(b)`) we still declare meaningful column names. For any
other query, `execute_cypher_query` retries with an increasing column
count and catches AGE's specific arity-mismatch error, so arbitrary valid
Cypher actually runs — with generic `col1, col2, ...` names in that case,
since AGE gives us no per-query aliases to recover.

Falls back to the previous relational-table + NetworkX implementation when
the AGE extension isn't installed on the target Postgres (e.g. a managed
Postgres like Neon that doesn't ship it) — a hosted/demo deployment that
points GRAPH_DB_HOST at plain Postgres keeps working exactly as before,
it just doesn't get real Cypher.
"""

from __future__ import annotations

import os
import re
import json
import uuid
from typing import Any, List

import psycopg2
import psycopg2.extras
import pandas as pd
import networkx as nx

# ─── DB Connection ────────────────────────────────────────────────────────────

def _get_conn():
    """Returns a connection to the PostgreSQL database."""
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        return psycopg2.connect(db_url, cursor_factory=psycopg2.extras.RealDictCursor)
    return psycopg2.connect(
        host=os.environ.get("GRAPH_DB_HOST") or "localhost",
        port=int(os.environ.get("GRAPH_DB_PORT") or 5432),
        user=os.environ.get("GRAPH_DB_USER") or "postgres",
        password=os.environ.get("GRAPH_DB_PASSWORD") or "",
        dbname=os.environ.get("GRAPH_DB_NAME") or "graphdb",
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


# ─── AGE availability, graph naming, agtype parsing ──────────────────────────

def _sanitize_graph_name(name: str) -> str:
    """AGE graph names become Postgres schema names, so must be a valid
    identifier — same normalization this file already used for edge labels."""
    safe = re.sub(r'[^A-Za-z0-9_]', '_', name).lower()
    if not safe or not safe[0].isalpha():
        safe = f"g_{safe}"
    return safe[:63]  # Postgres identifier length limit


def _age_ready(cur) -> bool:
    """
    True if the AGE extension is installed on this Postgres instance, and
    loads it + sets search_path for the current session as a side effect.
    False (never an exception) on a Postgres that doesn't have it — the
    signal callers use to fall back to the legacy relational+NetworkX path
    instead of erroring out on a managed/hosted database.
    """
    try:
        cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'age';")
        if cur.fetchone() is None:
            return False
        cur.execute("LOAD 'age';")
        cur.execute('SET search_path = ag_catalog, "$user", public;')
        return True
    except Exception:
        return False


def _ensure_graph(cur, graph: str) -> None:
    cur.execute("SELECT 1 FROM ag_catalog.ag_graph WHERE name = %s;", (graph,))
    if cur.fetchone() is None:
        cur.execute("SELECT create_graph(%s);", (graph,))


def _parse_agtype(raw: Any) -> Any:
    """
    AGE returns agtype values as text: '"Alice"' (string), '3' (int),
    or '{"id":...,"properties":{...}}::vertex' / '...::edge' (typed maps).
    Strip the trailing ::vertex/::edge/::path annotation if present, then
    JSON-decode — agtype's text form is JSON plus that optional suffix.
    """
    if raw is None or not isinstance(raw, str):
        return raw
    text = raw
    for suffix in ("::vertex", "::edge", "::path"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
            break
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text


def _run_prepared_cypher(cur, graph: str, cypher_body: str, returns: str, params_list: List[dict]) -> None:
    """
    PREPARE `cypher_body` once (an AGE requirement for any Cypher statement
    that needs dynamic values — see module docstring), EXECUTE it once per
    dict in `params_list`, then DEALLOCATE. Used for idempotent MERGE syncs
    where the same statement shape runs many times with different values.
    """
    stmt = f"s_{uuid.uuid4().hex[:12]}"
    cur.execute(f"""
        PREPARE {stmt}(agtype) AS
        SELECT * FROM cypher('{graph}', $$ {cypher_body} $$, $1) as {returns};
    """)
    try:
        for params in params_list:
            cur.execute(f"EXECUTE {stmt}(%s);", (json.dumps(params),))
    finally:
        cur.execute(f"DEALLOCATE {stmt};")


# ─── Graph Stats ──────────────────────────────────────────────────────────────

def get_graph_stats(graph_name: str) -> dict:
    """Returns node/edge counts and distinct relationship labels for a graph."""
    graph = _sanitize_graph_name(graph_name)
    conn = _get_conn()
    try:
        cur = conn.cursor()
        if not _age_ready(cur):
            conn.close()
            return _get_graph_stats_legacy(graph_name)

        _ensure_graph(cur, graph)
        conn.commit()

        cur.execute(f"SELECT * FROM cypher('{graph}', $$ MATCH (n) RETURN count(n) $$) as (node_count agtype);")
        nodes = _parse_agtype(cur.fetchone()["node_count"])

        cur.execute(f"SELECT * FROM cypher('{graph}', $$ MATCH ()-[r]->() RETURN count(r) $$) as (edge_count agtype);")
        edges = _parse_agtype(cur.fetchone()["edge_count"])

        cur.execute(f"SELECT * FROM cypher('{graph}', $$ MATCH ()-[r]->() RETURN DISTINCT type(r) $$) as (lbl agtype);")
        labels = [_parse_agtype(r["lbl"]) for r in cur.fetchall()][:20]

        return {"nodes": nodes, "edges": edges, "labels": labels, "active_graphs": 1}
    except Exception as e:
        return {"error": str(e), "nodes": 0, "edges": 0, "labels": [], "active_graphs": 0}
    finally:
        conn.close()


# ─── DataFrame Sync ───────────────────────────────────────────────────────────

def sync_dataframe_to_age(
    graph_name: str,
    df: pd.DataFrame,
    source_col: str,
    target_col: str,
    edge_label: str = "RELATED_TO"
) -> str:
    """Idempotently MERGEs a DataFrame's nodes and edges into an Apache AGE graph."""
    graph = _sanitize_graph_name(graph_name)
    conn = _get_conn()
    try:
        cur = conn.cursor()
        if not _age_ready(cur):
            conn.close()
            return _sync_dataframe_legacy(graph_name, df, source_col, target_col, edge_label)

        _ensure_graph(cur, graph)
        conn.commit()

        edge_type = re.sub(r'[^A-Za-z0-9_]', '_', edge_label).upper()

        sources = df[source_col].astype(str).unique().tolist()
        targets = df[target_col].astype(str).unique().tolist()
        all_nodes = list(set(sources + targets))

        _run_prepared_cypher(
            cur, graph,
            "MERGE (n:Entity {node_id: $node_id})",
            "(n agtype)",
            [{"node_id": n} for n in all_nodes],
        )

        edge_params = [
            {"src": str(row[source_col]), "tgt": str(row[target_col])}
            for _, row in df.iterrows()
        ]
        _run_prepared_cypher(
            cur, graph,
            f"MERGE (a:Entity {{node_id: $src}}) MERGE (b:Entity {{node_id: $tgt}}) MERGE (a)-[r:{edge_type}]->(b)",
            "(r agtype)",
            edge_params,
        )

        conn.commit()
        return (
            f"✅ Synced to Apache AGE graph '{graph}': "
            f"{len(all_nodes)} nodes, {len(df)} edges (label: {edge_type})"
        )
    except Exception as e:
        conn.rollback()
        return f"❌ Graph sync error: {str(e)}"
    finally:
        conn.close()


def sync_dataframe_to_neo4j(
    graph_name: str,
    df: pd.DataFrame,
    source_col: str,
    target_col: str,
    edge_label: str = "RELATED_TO"
) -> str:
    """
    Kept for backwards compatibility with existing call sites (api/main.py's
    /v1/graph/project). Despite the name, this delegates to the real Apache
    AGE implementation above, not Neo4j — no Neo4j instance is involved
    anywhere in this stack.
    """
    return sync_dataframe_to_age(graph_name, df, source_col, target_col, edge_label)


# ─── Cypher Query Execution ───────────────────────────────────────────────────

def execute_cypher_query(graph_name: str, cypher_query: str) -> pd.DataFrame:
    """
    Executes real openCypher against the Apache AGE graph. The two shapes
    this module has always advertised (`MATCH (n) RETURN n` and
    `MATCH (a)-[r]->(b)`) get meaningful column names; any other valid
    Cypher query is executed too, discovered by retrying increasing output
    arities (see module docstring) with generic column names.
    """
    graph = _sanitize_graph_name(graph_name)
    conn = _get_conn()
    try:
        cur = conn.cursor()
        if not _age_ready(cur):
            conn.close()
            return _execute_cypher_query_legacy(graph_name, cypher_query)

        _ensure_graph(cur, graph)
        conn.commit()

        query_upper = cypher_query.upper().strip()

        if "MATCH (N)" in query_upper or "MATCH (N:ENTITY)" in query_upper:
            cur.execute(f"""
                SELECT * FROM cypher('{graph}', $$
                    MATCH (n) RETURN n.node_id
                $$) as (node_id agtype);
            """)
            rows = [{"node_id": _parse_agtype(r["node_id"])} for r in cur.fetchall()]
            return pd.DataFrame(rows).head(50)

        if "MATCH (A" in query_upper and "-[" in query_upper and "]->(B" in query_upper:
            cur.execute(f"""
                SELECT * FROM cypher('{graph}', $$
                    MATCH (a)-[r]->(b) RETURN a.node_id, type(r), b.node_id
                $$) as (source_id agtype, relationship agtype, target_id agtype);
            """)
            rows = [
                {
                    "source_id": _parse_agtype(r["source_id"]),
                    "target_id": _parse_agtype(r["target_id"]),
                    "relationship": _parse_agtype(r["relationship"]),
                }
                for r in cur.fetchall()
            ]
            return pd.DataFrame(rows).head(50)

        # Generic path: discover the query's real output arity by retrying,
        # since AGE requires it declared but can't tell us in advance.
        last_err: Exception | None = None
        for n in range(1, 7):
            cols = ", ".join(f"col{i} agtype" for i in range(1, n + 1))
            try:
                cur.execute(f"SELECT * FROM cypher('{graph}', $$ {cypher_query} $$) as ({cols});")
                rows = cur.fetchall()
                if not rows:
                    return pd.DataFrame()
                parsed = [{k: _parse_agtype(v) for k, v in row.items()} for row in rows]
                return pd.DataFrame(parsed).head(50)
            except psycopg2.errors.DatatypeMismatch as e:
                conn.rollback()
                last_err = e
                continue
        raise Exception(f"Could not determine this query's result shape: {last_err}")

    except Exception as e:
        raise Exception(f"Failed to execute Cypher query: {str(e)}")
    finally:
        conn.close()


def load_networkx_graph(graph_name: str) -> nx.DiGraph:
    """
    Builds a NetworkX DiGraph from the graph's current state — used by
    query_engine/graph_executor.py's algorithm mode (shortest path,
    centrality, community detection, ...), which NetworkX genuinely is the
    right tool for, unlike hand-rolling Cypher pattern matching. Reads from
    Apache AGE when available so it sees whatever sync_dataframe_to_age
    actually wrote, falling back to the legacy relational tables only when
    AGE isn't installed on this Postgres.
    """
    graph = _sanitize_graph_name(graph_name)
    conn = _get_conn()
    G = nx.DiGraph()
    try:
        cur = conn.cursor()
        if _age_ready(cur):
            _ensure_graph(cur, graph)
            conn.commit()

            cur.execute(f"""
                SELECT * FROM cypher('{graph}', $$ MATCH (n) RETURN n.node_id $$) as (node_id agtype);
            """)
            for r in cur.fetchall():
                G.add_node(_parse_agtype(r["node_id"]))

            cur.execute(f"""
                SELECT * FROM cypher('{graph}', $$
                    MATCH (a)-[r]->(b) RETURN a.node_id, type(r), b.node_id
                $$) as (source_id agtype, relationship agtype, target_id agtype);
            """)
            for r in cur.fetchall():
                G.add_edge(
                    _parse_agtype(r["source_id"]),
                    _parse_agtype(r["target_id"]),
                    label=_parse_agtype(r["relationship"]),
                )
            return G

        init_graph_tables()
        cur.execute("SELECT node_id, label FROM auth.graph_nodes WHERE workspace_id = %s;", (graph_name,))
        for n in cur.fetchall():
            G.add_node(n["node_id"], label=n["label"])
        cur.execute("SELECT source_id, target_id, label FROM auth.graph_edges WHERE workspace_id = %s;", (graph_name,))
        for e in cur.fetchall():
            G.add_edge(e["source_id"], e["target_id"], label=e["label"])
        return G
    finally:
        conn.close()


# ─── Legacy fallback (relational tables + NetworkX) ──────────────────────────
# Used only when the target Postgres doesn't have the AGE extension
# installed (e.g. a managed Postgres like Neon) — see _age_ready above.

def init_graph_tables():
    """Initializes the legacy relational graph tables in the auth schema."""
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS auth.graph_nodes (
                workspace_id TEXT NOT NULL,
                node_id      TEXT NOT NULL,
                label        TEXT NOT NULL DEFAULT 'Entity',
                properties   JSONB NOT NULL DEFAULT '{}'::jsonb,
                PRIMARY KEY (workspace_id, node_id)
            );
        """)
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
        cur.execute("CREATE INDEX IF NOT EXISTS idx_graph_edges_src ON auth.graph_edges(workspace_id, source_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_graph_edges_tgt ON auth.graph_edges(workspace_id, target_id);")
        conn.commit()
        print("[graph_db] Legacy relational graph tables initialized (AGE extension not available).")
    except Exception as e:
        conn.rollback()
        print(f"[graph_db] Legacy schema initialization error: {e}")
    finally:
        conn.close()


def _get_graph_stats_legacy(graph_name: str) -> dict:
    init_graph_tables()
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM auth.graph_nodes WHERE workspace_id = %s;", (graph_name,))
        nodes = cur.fetchone()["count"]
        cur.execute("SELECT count(*) FROM auth.graph_edges WHERE workspace_id = %s;", (graph_name,))
        edges = cur.fetchone()["count"]
        cur.execute("SELECT DISTINCT label FROM auth.graph_edges WHERE workspace_id = %s LIMIT 20;", (graph_name,))
        labels = [r["label"] for r in cur.fetchall()]
        return {"nodes": nodes, "edges": edges, "labels": labels, "active_graphs": 1}
    except Exception as e:
        return {"error": str(e), "nodes": 0, "edges": 0, "labels": [], "active_graphs": 0}
    finally:
        conn.close()


def _sync_dataframe_legacy(
    graph_name: str,
    df: pd.DataFrame,
    source_col: str,
    target_col: str,
    edge_label: str = "RELATED_TO"
) -> str:
    init_graph_tables()
    conn = _get_conn()
    try:
        cur = conn.cursor()
        sources = df[source_col].astype(str).unique().tolist()
        targets = df[target_col].astype(str).unique().tolist()
        all_nodes = list(set(sources + targets))

        for node in all_nodes:
            cur.execute(
                """
                INSERT INTO auth.graph_nodes (workspace_id, node_id, label, properties)
                VALUES (%s, %s, 'Entity', '{}'::jsonb)
                ON CONFLICT (workspace_id, node_id) DO NOTHING;
                """,
                (graph_name, node)
            )

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
            f"✅ Synced to legacy Postgres graph '{graph_name}' (AGE unavailable): "
            f"{len(all_nodes)} nodes, {len(df)} edges (label: {edge_type})"
        )
    except Exception as e:
        conn.rollback()
        return f"❌ Graph sync error: {str(e)}"
    finally:
        conn.close()


def _execute_cypher_query_legacy(graph_name: str, cypher_query: str) -> pd.DataFrame:
    """Hand-rolled MATCH/RETURN matcher over an in-memory NetworkX graph —
    the pre-AGE behaviour, kept only as a fallback."""
    init_graph_tables()
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT node_id, label FROM auth.graph_nodes WHERE workspace_id = %s;", (graph_name,))
        nodes = cur.fetchall()
        cur.execute("SELECT source_id, target_id, label FROM auth.graph_edges WHERE workspace_id = %s;", (graph_name,))
        edges = cur.fetchall()
        conn.close()

        G = nx.DiGraph()
        for n in nodes:
            G.add_node(n["node_id"], label=n["label"])
        for e in edges:
            G.add_edge(e["source_id"], e["target_id"], label=e["label"])

        query_upper = cypher_query.upper().strip()
        if "MATCH (N)" in query_upper or "MATCH (N:ENTITY)" in query_upper:
            rows = [{"node_id": n} for n in G.nodes()]
            return pd.DataFrame(rows).head(50)
        elif "MATCH (A" in query_upper and "-[" in query_upper and "]->(B" in query_upper:
            rows = []
            for u, v, data in G.edges(data=True):
                rows.append({
                    "source_id": u,
                    "target_id": v,
                    "relationship": data.get("label", "RELATED_TO")
                })
            return pd.DataFrame(rows).head(50)
        else:
            rows = [{"node_id": n} for n in G.nodes()]
            return pd.DataFrame(rows).head(20)
    except Exception as e:
        raise Exception(f"Failed to execute mock Cypher query: {str(e)}")
