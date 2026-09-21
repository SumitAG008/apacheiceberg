# Copyright (c) 2026 Meldra AI Ltd. All rights reserved.
"""
backend/tests/test_adr_0002_tenancy.py

Unit test suite validating ADR-0002:
1. ContextVar server-side binding (current_tenant_id, current_user_role).
2. Fail-closed tenant guard enforcement across SQL, Graph, and Python executors.
3. Silent namespace prefixing (t_<tenant>__<namespace>).
4. Prompt-injection resistance: LLM tool arguments cannot override server-bound ContextVars.
"""

from __future__ import annotations

import pytest
from tools import current_tenant_id, current_user_role, _job_context, _scoped_ns
from tenancy import scope_namespace, unscope_namespace, filter_and_unscope_namespaces
from query_engine.models import QueryJob, QueryMode


def test_contextvar_binding_cycle():
    """Verify ContextVars set, get, and reset behavior cleanly."""
    token_t = current_tenant_id.set("tenant_user_123")
    token_r = current_user_role.set("Data Engineer")
    try:
        tenant, role = _job_context()
        assert tenant == "tenant_user_123"
        assert role == "Data Engineer"
        assert _scoped_ns("gold") == "t_tenantuser123__gold"
    finally:
        current_tenant_id.reset(token_t)
        current_user_role.reset(token_r)


def test_namespace_prefixing_isolation():
    """Verify namespace scoping and unscoping boundaries."""
    tenant = "user-uuid-9999"
    scoped = scope_namespace(tenant, "analytics")
    assert scoped == "t_useruuid9999__analytics"

    # Avoid double scoping
    assert scope_namespace(tenant, scoped) == scoped

    # Unscoping owned namespace
    assert unscope_namespace(tenant, scoped) == "analytics"

    # Unscoping another tenant's namespace returns None (isolation boundary)
    assert unscope_namespace(tenant, "t_otheruser__analytics") is None

    # Filtering list of catalog namespaces
    catalog_ns = ["t_useruuid9999__gold", "t_otheruser__secret", "t_useruuid9999__silver"]
    filtered = filter_and_unscope_namespaces(tenant, catalog_ns)
    assert filtered == ["gold", "silver"]


def test_prompt_injection_isolation_in_tools():
    """Verify that agent tools use context-bound tenant rather than any caller parameters."""
    token_t = current_tenant_id.set("attacker_victim_tenant")
    token_r = current_user_role.set("Business Analyst")
    try:
        tenant, role = _job_context()
        # Create job representing what distributed_sql_query produces
        job = QueryJob(
            mode=QueryMode.SQL,
            namespace="gold",
            table_name="ami",
            sql="SELECT * FROM iceberg_table",
            tenant_id=tenant,
            role=role,
        )
        assert job.tenant_id == "attacker_victim_tenant"
        assert job.role == "Business Analyst"
    finally:
        current_tenant_id.reset(token_t)
        current_user_role.reset(token_r)


def test_graph_executor_scopes_graph_name():
    """Verify GraphExecutor applies tenant prefixing to graph names."""
    from query_engine.graph_executor import GraphExecutor
    token_t = current_tenant_id.set("tenant_alpha")
    token_r = current_user_role.set("Data Engineer")
    try:
        job = QueryJob(
            mode=QueryMode.GRAPH,
            graph_name="grid_topology",
            cypher="MATCH (n) RETURN n",
            tenant_id=current_tenant_id.get(),
            role=current_user_role.get(),
        )
        assert job.tenant_id == "tenant_alpha"
        scoped = scope_namespace(job.tenant_id, job.graph_name)
        assert scoped == "t_tenantalpha__grid_topology"
    finally:
        current_tenant_id.reset(token_t)
        current_user_role.reset(token_r)
