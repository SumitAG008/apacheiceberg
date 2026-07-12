# Copyright (c) 2025 Meldra AI Ltd. All rights reserved.
"""
rbac_utils.py — RBAC enforcement applied at the data layer.

Three layers, applied in order, all *before* a DataFrame is registered with
DuckDB or handed to the Python sandbox -- so nothing downstream (aliasing a
column, wrapping a query in a subquery, renaming in a SELECT list) can
bypass a policy. Each layer acts on the data itself, not on trusting the
query to behave:

  1. Table/namespace access  -- can this role see this table at all?
  2. Row-level filtering     -- which rows is this role allowed to see?
  3. Column masking/denial   -- which columns are redacted or dropped?

Call `enforce_rbac(df, namespace, table_name, role)` as the single entry
point; it runs all three layers and returns the DataFrame every query path
should actually operate on.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd


class TableAccessDenied(PermissionError):
    """Raised when a role has no access to a table/namespace at all."""


# ─── Fetching policies ────────────────────────────────────────────────────

def get_role_policies(role: str) -> List[Dict[str, Any]]:
    """Fetch all column/table policies configured for a given role."""
    from auth_db import _get_conn

    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT namespace, table_name, column_name, action, masking_pattern "
            "FROM auth.rbac_policies WHERE role = %s;",
            (role,),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_row_filters(role: str) -> List[Dict[str, Any]]:
    """Fetch all row-level filters configured for a given role."""
    from auth_db import _get_conn

    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT namespace, table_name, filter_expression, description "
            "FROM auth.rbac_row_filters WHERE role = %s;",
            (role,),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


# ─── Layer 1: table/namespace access ──────────────────────────────────────

TABLE_DENY_SENTINEL = "__TABLE__"


def check_table_access(namespace: str, table_name: str, role: str) -> None:
    """
    Raise TableAccessDenied if `role` has a whole-table or whole-namespace
    deny policy for namespace.table_name. A policy with column_name =
    '__TABLE__' and table_name = the real table (or '*' for every table in
    the namespace) denies access outright, before any query runs.
    """
    policies = get_role_policies(role)
    for pol in policies:
        if pol["column_name"] != TABLE_DENY_SENTINEL or pol["action"] != "deny":
            continue
        if pol["namespace"] not in (namespace, "*"):
            continue
        if pol["table_name"] not in (table_name, "*"):
            continue
        raise TableAccessDenied(
            f"Access Denied: role '{role}' is not authorized to access {namespace}.{table_name}."
        )


# ─── Layer 2: row-level filtering ─────────────────────────────────────────

def apply_row_filters(
    df: pd.DataFrame,
    namespace: str,
    table_name: str,
    role: str,
) -> pd.DataFrame:
    """
    Apply every row filter configured for `role` against this table,
    combined with AND (a role only sees rows that satisfy every applicable
    filter). Filters are plain pandas .query() expressions authored by an
    Admin -- the same trust boundary as masking_pattern values -- not
    user-controlled at query time.
    """
    filters = get_row_filters(role)
    if not filters:
        return df

    for f in filters:
        if f["namespace"] not in (namespace, "*"):
            continue
        if f["table_name"] not in (table_name, "*"):
            continue
        try:
            df = df.query(f["filter_expression"])
        except Exception:
            # A misconfigured filter (e.g. referencing a column this table
            # doesn't have) must fail closed, not silently show everything.
            df = df.iloc[0:0]

    return df


# ─── Layer 3: column masking/denial ───────────────────────────────────────

def apply_rbac_to_dataframe(
    df: pd.DataFrame,
    namespace: str,
    table_name: str,
    role: str,
) -> pd.DataFrame:
    """
    Apply column-level policies for `role` against `namespace.table_name`,
    returning a new DataFrame with denied columns dropped and masked
    columns redacted in place. Matches policies scoped to this table name
    or to '*' (wildcard, applies to every table for that role). Skips the
    '__TABLE__' sentinel used for whole-table denial (see check_table_access).
    """
    policies = get_role_policies(role)
    if not policies:
        return df

    df = df.copy()
    for pol in policies:
        col = pol["column_name"]
        if col == TABLE_DENY_SENTINEL:
            continue
        tbl_scope = pol["table_name"]
        if tbl_scope not in (table_name, "*"):
            continue
        if col not in df.columns:
            continue

        if pol["action"] == "deny":
            df = df.drop(columns=[col])
        elif pol["action"] == "mask":
            pattern = pol["masking_pattern"]
            df[col] = df[col].astype(object)
            if pattern == "###.##":
                df[col] = 0.0
            elif pattern == "***":
                df[col] = "***"
            else:
                df[col] = df[col].apply(lambda x, p=pattern: p if pd.notna(x) else None)

    return df


def denied_columns(namespace: str, table_name: str, role: str) -> List[str]:
    """Return column names the given role is denied from seeing on this table."""
    policies = get_role_policies(role)
    return [
        p["column_name"]
        for p in policies
        if p["action"] == "deny"
        and p["column_name"] != TABLE_DENY_SENTINEL
        and p["table_name"] in (table_name, "*")
    ]


# ─── Combined entry point ──────────────────────────────────────────────────

def enforce_rbac(
    df: pd.DataFrame,
    namespace: str,
    table_name: str,
    role: str,
) -> pd.DataFrame:
    """
    Run all three RBAC layers in order: table access, then row filtering,
    then column masking/denial. This is the single function every query
    path (SQL console, DQE SQLExecutor, DQE PythonExecutor) should call
    instead of applying layers individually, so a new caller can't
    accidentally skip one.

    Raises TableAccessDenied if the role has no access to this table at
    all -- callers should catch this and return a 403, not a 500.
    """
    check_table_access(namespace, table_name, role)
    df = apply_row_filters(df, namespace, table_name, role)
    df = apply_rbac_to_dataframe(df, namespace, table_name, role)
    return df
