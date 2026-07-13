# Copyright (c) 2025 Meldra AI Ltd. All rights reserved.
"""
query_engine/graph_executor.py — Graph query execution engine.

Loads the graph (from Apache AGE, or the legacy relational tables if AGE
isn't installed — see graph_db.load_networkx_graph) into a NetworkX
DiGraph, evaluates Cypher-like MATCH patterns, and runs graph algorithms.
Returns normalised QueryResult objects.

Supported query patterns:
  - MATCH (n) RETURN n [LIMIT x]
  - MATCH (a)-[r]->(b) [WHERE r.label = '...'] RETURN a.node_id, b.node_id [LIMIT x]
  - ALGORITHM: pagerank | betweenness_centrality | degree_centrality |
               connected_components | shortest_path | find_cycles

Returns both tabular rows AND graph topology JSON for visualisation.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import networkx as nx
import pandas as pd

from query_engine.models import QueryJob, QueryResult

logger = logging.getLogger(__name__)


# ─── Cypher mini-parser ───────────────────────────────────────────────────────

_NODE_PATTERN     = re.compile(r"MATCH\s*\((\w+)(?::(\w+))?\)", re.IGNORECASE)
_EDGE_PATTERN     = re.compile(
    r"MATCH\s*\((\w+)(?::(\w+))?\)\s*-\[(\w+)(?::(\w+))?\]->\s*\((\w+)(?::(\w+))?\)",
    re.IGNORECASE,
)
_WHERE_LABEL      = re.compile(r"WHERE\s+\w+\.label\s*=\s*['\"](\w+)['\"]", re.IGNORECASE)
_WHERE_NODE_PROP  = re.compile(r"WHERE\s+\w+\.node_id\s*=\s*['\"]([^'\"]+)['\"]", re.IGNORECASE)
_LIMIT_PATTERN    = re.compile(r"LIMIT\s+(\d+)", re.IGNORECASE)
_RETURN_DISTINCT  = re.compile(r"\bDISTINCT\b", re.IGNORECASE)


def _extract_limit(cypher: str, default: int) -> int:
    m = _LIMIT_PATTERN.search(cypher)
    return int(m.group(1)) if m else default


def _extract_label_filter(cypher: str) -> Optional[str]:
    m = _WHERE_LABEL.search(cypher)
    return m.group(1).upper() if m else None


def _extract_node_filter(cypher: str) -> Optional[str]:
    m = _WHERE_NODE_PROP.search(cypher)
    return m.group(1) if m else None


class GraphExecutor:
    """
    Executes graph queries and algorithms against the PostgreSQL-backed graph store.
    """

    def execute(self, job: QueryJob) -> QueryResult:
        t0 = time.perf_counter()
        G = self._load_graph(job.graph_name)

        if job.algorithm:
            result = self._run_algorithm(G, job)
        else:
            result = self._run_cypher(G, job)

        duration_ms = int((time.perf_counter() - t0) * 1000)
        result.duration_ms = duration_ms
        return result

    def explain(self, job: QueryJob) -> str:
        G = self._load_graph(job.graph_name)
        node_count = G.number_of_nodes()
        edge_count = G.number_of_edges()
        if job.algorithm:
            return (
                f"[DQE/GRAPH] Algorithm: {job.algorithm} | "
                f"Graph: {job.graph_name} | Nodes: {node_count} | Edges: {edge_count}\n"
                f"Will run NetworkX {job.algorithm} on the full in-memory DiGraph."
            )
        return (
            f"[DQE/GRAPH] Cypher pattern match | "
            f"Graph: {job.graph_name} | Nodes: {node_count} | Edges: {edge_count}\n"
            f"Query: {job.cypher}"
        )

    # ─── Cypher execution ─────────────────────────────────────────────────────

    def _run_cypher(self, G: nx.DiGraph, job: QueryJob) -> QueryResult:
        cypher = job.cypher.strip()
        limit = job.limit
        distinct = bool(_RETURN_DISTINCT.search(cypher))
        edge_filter = _extract_label_filter(cypher)
        node_filter = _extract_node_filter(cypher)

        q_upper = cypher.upper()

        # ── Pattern: MATCH (a)-[r]->(b) ── edge traversal ─────────────────────
        if _EDGE_PATTERN.search(cypher) or ("->(" in cypher and "-[" in cypher):
            rows: List[Dict[str, Any]] = []
            for u, v, data in G.edges(data=True):
                label = data.get("label", "RELATED_TO")
                if edge_filter and label != edge_filter:
                    continue
                rows.append({
                    "source_id": u,
                    "target_id": v,
                    "relationship": label,
                })
            if distinct:
                seen: set = set()
                deduped = []
                for r in rows:
                    key = (r["source_id"], r["target_id"], r["relationship"])
                    if key not in seen:
                        seen.add(key)
                        deduped.append(r)
                rows = deduped
            truncated = len(rows) > limit
            rows = rows[:limit]
            plan = (
                f"[DQE/GRAPH] Edge traversal | "
                f"Nodes: {G.number_of_nodes()} | Edges scanned: {G.number_of_edges()} | "
                f"Label filter: {edge_filter or 'none'} | "
                f"Engine: NetworkX {nx.__version__}"
            )
            return QueryResult(
                columns=["source_id", "target_id", "relationship"],
                rows=rows,
                total_rows=G.number_of_edges(),
                truncated=truncated,
                execution_plan=plan,
                engine_used="networkx",
            )

        # ── Pattern: MATCH (n) ── node listing ────────────────────────────────
        nodes = list(G.nodes(data=True))
        if node_filter:
            nodes = [(nid, d) for nid, d in nodes if nid == node_filter]
        rows = []
        for node_id, data in nodes:
            rows.append({
                "node_id": node_id,
                "label": data.get("label", "Entity"),
                "degree": G.degree(node_id),
                "in_degree": G.in_degree(node_id),
                "out_degree": G.out_degree(node_id),
            })
        truncated = len(rows) > limit
        rows = rows[:limit]
        plan = (
            f"[DQE/GRAPH] Node scan | Total nodes: {G.number_of_nodes()} | "
            f"Filter: {node_filter or 'none'} | Engine: NetworkX {nx.__version__}"
        )
        return QueryResult(
            columns=["node_id", "label", "degree", "in_degree", "out_degree"],
            rows=rows,
            total_rows=G.number_of_nodes(),
            truncated=truncated,
            execution_plan=plan,
            engine_used="networkx",
        )

    # ─── Algorithm execution ──────────────────────────────────────────────────

    def _run_algorithm(self, G: nx.DiGraph, job: QueryJob) -> QueryResult:
        algo = job.algorithm.lower()
        limit = job.limit

        if algo == "pagerank":
            scores = nx.pagerank(G, alpha=0.85, max_iter=200)
            rows = [
                {"node_id": n, "pagerank_score": round(s, 6)}
                for n, s in sorted(scores.items(), key=lambda x: -x[1])
            ]
            plan = f"[DQE/GRAPH] PageRank (alpha=0.85) on {G.number_of_nodes()} nodes"
            columns = ["node_id", "pagerank_score"]

        elif algo == "betweenness_centrality":
            scores = nx.betweenness_centrality(G, normalized=True)
            rows = [
                {"node_id": n, "betweenness": round(s, 6)}
                for n, s in sorted(scores.items(), key=lambda x: -x[1])
            ]
            plan = f"[DQE/GRAPH] Betweenness Centrality on {G.number_of_nodes()} nodes"
            columns = ["node_id", "betweenness"]

        elif algo == "degree_centrality":
            scores = nx.degree_centrality(G)
            rows = [
                {"node_id": n, "degree_centrality": round(s, 6)}
                for n, s in sorted(scores.items(), key=lambda x: -x[1])
            ]
            plan = f"[DQE/GRAPH] Degree Centrality on {G.number_of_nodes()} nodes"
            columns = ["node_id", "degree_centrality"]

        elif algo == "connected_components":
            UG = G.to_undirected()
            components = list(nx.connected_components(UG))
            rows = []
            for i, comp in enumerate(sorted(components, key=len, reverse=True)):
                rows.append({
                    "component_id": i + 1,
                    "size": len(comp),
                    "sample_nodes": ", ".join(list(comp)[:5]),
                })
            plan = (
                f"[DQE/GRAPH] Connected Components on undirected projection | "
                f"Total components: {len(components)}"
            )
            columns = ["component_id", "size", "sample_nodes"]

        elif algo == "find_cycles":
            cycles = list(nx.simple_cycles(G))
            meaningful = [c for c in cycles if len(c) > 2]
            rows = []
            for i, ring in enumerate(meaningful):
                path = " → ".join(str(x) for x in ring) + f" → {ring[0]}"
                rows.append({"cycle_id": i + 1, "length": len(ring), "path": path})
            plan = (
                f"[DQE/GRAPH] Cycle Detection | "
                f"Total simple cycles: {len(cycles)} | Meaningful (>2 hops): {len(meaningful)}"
            )
            columns = ["cycle_id", "length", "path"]
            if not rows:
                rows = [{"cycle_id": 0, "length": 0, "path": "No cycles detected"}]

        elif algo == "shortest_path":
            # Requires source/target passed via filters
            filters = job.filters or {}
            source = filters.get("source")
            target = filters.get("target")
            if not source or not target:
                raise ValueError(
                    "shortest_path algorithm requires filters={'source': '...', 'target': '...'}"
                )
            try:
                path = nx.shortest_path(G, source=source, target=target)
                rows = [{"hop": i, "node_id": n} for i, n in enumerate(path)]
                plan = f"[DQE/GRAPH] Shortest Path: {source} → {target} | Length: {len(path)}"
            except nx.NetworkXNoPath:
                rows = [{"hop": -1, "node_id": f"No path from {source} to {target}"}]
                plan = f"[DQE/GRAPH] Shortest Path: No path found between {source} and {target}"
            columns = ["hop", "node_id"]

        elif algo == "community_detection":
            try:
                import community as community_louvain  # python-louvain
                UG = G.to_undirected()
                partition = community_louvain.best_partition(UG)
                by_community: Dict[int, List[str]] = {}
                for node, comm in partition.items():
                    by_community.setdefault(comm, []).append(node)
                rows = [
                    {
                        "community_id": cid,
                        "size": len(members),
                        "sample_nodes": ", ".join(members[:5]),
                    }
                    for cid, members in sorted(by_community.items())
                ]
                plan = (
                    f"[DQE/GRAPH] Louvain Community Detection | "
                    f"Communities: {len(by_community)}"
                )
                columns = ["community_id", "size", "sample_nodes"]
            except ImportError:
                # Fallback to greedy modularity
                UG = G.to_undirected()
                communities = list(nx.algorithms.community.greedy_modularity_communities(UG))
                rows = [
                    {
                        "community_id": i + 1,
                        "size": len(c),
                        "sample_nodes": ", ".join(list(c)[:5]),
                    }
                    for i, c in enumerate(communities)
                ]
                plan = (
                    f"[DQE/GRAPH] Greedy Modularity Community Detection | "
                    f"Communities: {len(communities)}"
                )
                columns = ["community_id", "size", "sample_nodes"]
        else:
            raise ValueError(
                f"Unknown algorithm '{algo}'. Supported: pagerank, betweenness_centrality, "
                "degree_centrality, connected_components, find_cycles, shortest_path, "
                "community_detection"
            )

        total_rows = len(rows)
        truncated = total_rows > limit
        rows = rows[:limit]
        return QueryResult(
            columns=columns,
            rows=rows,
            total_rows=total_rows,
            truncated=truncated,
            execution_plan=plan,
            engine_used="networkx",
        )

    # ─── Graph loader ─────────────────────────────────────────────────────────

    @staticmethod
    def _load_graph(graph_name: str) -> nx.DiGraph:
        """Load the graph into a NetworkX DiGraph via graph_db, which reads
        from Apache AGE (falling back to the legacy relational tables only
        if AGE isn't installed) — see graph_db.load_networkx_graph."""
        import sys, os
        backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if backend_root not in sys.path:
            sys.path.insert(0, backend_root)

        from graph_db import load_networkx_graph

        G = load_networkx_graph(graph_name)

        logger.info(
            "[GraphExecutor] Loaded graph '%s': %d nodes, %d edges",
            graph_name, G.number_of_nodes(), G.number_of_edges(),
        )
        return G
