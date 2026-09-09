# Copyright (c) 2025-2026 Meldra AI Ltd. All rights reserved.
"""
tests/test_graph_scaling.py — Verification for graph algorithm scaling and neighborhood scoping.
"""

import networkx as nx
import pytest
from query_engine.graph_executor import GraphExecutor
from query_engine.models import QueryJob


def test_pagerank_with_max_iter():
    executor = GraphExecutor()
    G = nx.DiGraph()
    G.add_edges_from([("A", "B"), ("B", "C"), ("C", "A"), ("A", "D")])

    job = QueryJob(
        mode="graph",
        graph_name="test_graph",
        algorithm="pagerank",
        filters={"max_iter": 50, "tol": 1e-3},
    )

    res = executor._run_algorithm(G, job)
    assert len(res.rows) == 4
    assert res.columns == ["node_id", "pagerank_score"]
    assert "PageRank" in res.execution_plan


def test_approximate_betweenness_centrality():
    executor = GraphExecutor()
    G = nx.path_graph(10, create_using=nx.DiGraph)

    job = QueryJob(
        mode="graph",
        graph_name="test_graph",
        algorithm="betweenness_centrality",
        filters={"sample_k": 3},
    )

    res = executor._run_algorithm(G, job)
    assert len(res.rows) == 10
    assert "approximate k=3" in res.execution_plan


def test_subgraph_neighborhood_scoping():
    executor = GraphExecutor()
    G = nx.path_graph(10, create_using=nx.DiGraph)  # 0 -> 1 -> ... -> 9

    job = QueryJob(
        mode="graph",
        graph_name="test_graph",
        algorithm="degree_centrality",
        filters={"center": 3, "radius": 1},
    )

    res = executor._run_algorithm(G, job)
    # 1-hop from node 3 in directed path has 2 nodes: 3 and 4
    assert len(res.rows) <= 3


def test_quantum_qubo_partitioning():
    executor = GraphExecutor()
    G = nx.cycle_graph(6, create_using=nx.Graph)  # 6-node cycle

    job = QueryJob(
        mode="graph",
        graph_name="test_graph",
        algorithm="qubo_partitioning",
        filters={"sweeps": 150},
    )

    res = executor._run_algorithm(G, job)
    assert len(res.rows) == 2
    assert "QUBO / Max-Cut" in res.execution_plan
    assert "QAOA Circuit" in res.execution_plan


def test_ai_node_embeddings_and_link_prediction():
    executor = GraphExecutor()
    G = nx.karate_club_graph()

    # Test Node Embeddings
    job_emb = QueryJob(
        mode="graph",
        graph_name="test_graph",
        algorithm="node_embeddings",
        filters={"dimensions": 8},
    )
    res_emb = executor._run_algorithm(G, job_emb)
    assert len(res_emb.rows) == 34
    assert res_emb.columns == ["node_id", "dimension", "embedding_sample"]

    # Test Link Prediction
    job_links = QueryJob(
        mode="graph",
        graph_name="test_graph",
        algorithm="link_prediction",
        filters={"top_k": 5, "metric": "adamic_adar"},
    )
    res_links = executor._run_algorithm(G, job_links)
    assert len(res_links.rows) <= 5
    assert res_links.columns == ["source", "target", "score", "metric"]

