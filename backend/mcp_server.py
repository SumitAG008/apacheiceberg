"""
Real Model Context Protocol (MCP) server for meldra's own internal domain —
the platform's Iceberg catalog, RBAC-aware query engine, and graph store.

This is a genuine MCP server (stdio transport, tool discovery via the real
MCP SDK) — not a UI mockup. Every tool below is a thin, authenticated HTTP
call to meldra's real, deployed, RBAC- and tenant-scoped REST API, so any
MCP client (Claude Desktop, Claude Code, another agent) that connects to it
sees exactly what a logged-in user of that role/tenant would see — nothing
fabricated, nothing pre-scripted.

Setup:
    1. Log into meldra, open Settings > API Access, click "Generate API
       Token" (POST /auth/api-token). Copy the token.
    2. Set environment variables for whatever client will launch this
       server:
           MELDRA_API_URL   (default: https://api.meldra.ai)
           MELDRA_API_TOKEN (required — the token from step 1)
    3. Point your MCP client at this file, e.g. in Claude Desktop's
       claude_desktop_config.json:
           {
             "mcpServers": {
               "meldra": {
                 "command": "python",
                 "args": ["/absolute/path/to/backend/mcp_server.py"],
                 "env": { "MELDRA_API_TOKEN": "<token>" }
               }
             }
           }

External systems (SAP, Snowflake, Salesforce, Oracle, IAM, fraud, etc.)
are intentionally not represented here — meldra doesn't have real
connections to those systems yet. Those become their own MCP servers as
they're actually built, not stand-ins in this one.
"""
import os
from typing import Any, Optional

import httpx
from mcp.server.fastmcp import FastMCP

MELDRA_API_URL = os.environ.get("MELDRA_API_URL", "https://api.meldra.ai").rstrip("/")
MELDRA_API_TOKEN = os.environ.get("MELDRA_API_TOKEN", "")

mcp = FastMCP(
    name="meldra",
    instructions=(
        "Tools for meldra's own Apache Iceberg lakehouse: catalog objects "
        "(namespaces/tables), RBAC-aware SQL queries, and the graph store. "
        "All calls are scoped to the authenticated tenant and role behind "
        "MELDRA_API_TOKEN — the same access that user has in the web app."
    ),
)


def _client() -> httpx.Client:
    if not MELDRA_API_TOKEN:
        raise RuntimeError(
            "MELDRA_API_TOKEN is not set. Generate one in meldra's Settings "
            "> API Access page and set it as an environment variable for "
            "this server."
        )
    return httpx.Client(
        base_url=MELDRA_API_URL,
        headers={"Authorization": f"Bearer {MELDRA_API_TOKEN}"},
        timeout=30.0,
    )


def _request(method: str, path: str, **kwargs: Any) -> Any:
    with _client() as client:
        resp = client.request(method, path, **kwargs)
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        raise RuntimeError(f"meldra API error ({resp.status_code}): {detail}")
    return resp.json()


@mcp.tool()
def list_namespaces() -> dict:
    """List the Iceberg namespaces visible to the authenticated tenant."""
    return _request("GET", "/v1/catalog/namespaces")


@mcp.tool()
def list_tables(namespace: str) -> dict:
    """List the tables inside an Iceberg namespace.

    Args:
        namespace: The namespace to list tables from (e.g. "default").
    """
    return _request("GET", f"/v1/catalog/namespaces/{namespace}/tables")


@mcp.tool()
def get_table_details(namespace: str, table_name: str) -> dict:
    """Get schema, row count, and snapshot metadata for an Iceberg table.

    Args:
        namespace: The table's namespace.
        table_name: The table name.
    """
    return _request(
        "GET", f"/v1/catalog/namespaces/{namespace}/tables/{table_name}"
    )


@mcp.tool()
def query_table(sql: str, namespace: str = "default", limit: int = 500) -> dict:
    """Run a DuckDB SQL query against an Iceberg table, with RBAC (row
    filtering + column masking) enforced server-side for the caller's role.

    Args:
        sql: The SQL query to run.
        namespace: The namespace the query targets.
        limit: Max rows to return.
    """
    return _request(
        "POST",
        "/v1/catalog/query",
        json={"sql": sql, "namespace": namespace},
    )


@mcp.tool()
def graph_stats(graph_name: str = "pharma_graph") -> dict:
    """Get node/edge counts for a graph in the graph store.

    Args:
        graph_name: The graph's name/namespace.
    """
    return _request("GET", "/v1/graph/stats", params={"graph_name": graph_name})


@mcp.tool()
def run_cypher(graph_name: str, cypher_query: str) -> dict:
    """Run a Cypher query against a graph in the graph store.

    Args:
        graph_name: The graph's name/namespace.
        cypher_query: The Cypher query to execute.
    """
    return _request(
        "POST",
        "/v1/graph/cypher",
        json={"graph_name": graph_name, "query": cypher_query},
    )


@mcp.tool()
def list_rbac_policies() -> list:
    """List configured RBAC column/table policies. Admin role only —
    fails with a permission error for other roles, same as the web UI."""
    return _request("GET", "/v1/rbac/policies")


@mcp.tool()
def list_recent_audit_events() -> list:
    """List recent audit log events for the authenticated tenant."""
    return _request("GET", "/v1/audit")


if __name__ == "__main__":
    mcp.run(transport="stdio")
