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

    A role can also be deny-by-default: a '__TABLE__' deny policy scoped to
    namespace='*', table_name='*' blocks everything, *unless* an 'allow'
    policy exists for this specific namespace/table — this is how the
    Consultant persona works (see roles.py): no access to anything until an
    Admin explicitly grants a namespace.
    """
    policies = get_role_policies(role)

    deny_all = any(
        p["column_name"] == TABLE_DENY_SENTINEL
        and p["action"] == "deny"
        and p["namespace"] == "*"
        and p["table_name"] == "*"
        for p in policies
    )
    if deny_all:
        explicit_allow = any(
            p["column_name"] == TABLE_DENY_SENTINEL
            and p["action"] == "allow"
            and p["namespace"] in (namespace, "*")
            and p["table_name"] in (table_name, "*")
            for p in policies
        )
        if not explicit_allow:
            raise TableAccessDenied(
                f"Access Denied: role '{role}' has no grant for {namespace}.{table_name}."
            )

    for pol in policies:
        if pol["column_name"] != TABLE_DENY_SENTINEL or pol["action"] != "deny":
            continue
        if pol["namespace"] == "*" and pol["table_name"] == "*":
            continue  # already handled by the deny-all check above
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


import logging
import time

logger = logging.getLogger("meldra.rbac")


def enforce_rbac(
    df: pd.DataFrame,
    namespace: str,
    table_name: str,
    role: str,
    correlation_id: str | None = None,
) -> pd.DataFrame:
    """
    Run all three RBAC layers in order: table access, then row filtering,
    then column masking/denial. This is the single function every query
    path (SQL console, DQE SQLExecutor, DQE PythonExecutor) should call
    instead of applying layers individually, so a new caller can't
    accidentally skip one.

    Emits structured Customer Trust telemetry (rows filtered, columns masked/dropped)
    for security audit compliance.

    Raises TableAccessDenied if the role has no access to this table at
    all -- callers should catch this and return a 403, not a 500.
    """
    start_time = time.time()
    initial_rows = len(df)
    initial_cols = list(df.columns)

    check_table_access(namespace, table_name, role)
    df = apply_row_filters(df, namespace, table_name, role)
    df = apply_rbac_to_dataframe(df, namespace, table_name, role)

    elapsed_ms = round((time.time() - start_time) * 1000, 2)
    final_rows = len(df)
    final_cols = list(df.columns)
    dropped_cols = [c for c in initial_cols if c not in final_cols]

    logger.info(
        "RBAC Enforcement Telemetry | role=%s | table=%s.%s | correlation_id=%s | "
        "initial_rows=%d | final_rows=%d | dropped_cols=%s | duration_ms=%.2f",
        role,
        namespace,
        table_name,
        correlation_id or "N/A",
        initial_rows,
        final_rows,
        dropped_cols,
        elapsed_ms,
    )
    return df


# ─── Fast-path probe (zero-copy support) ──────────────────────────────────

def rbac_is_noop(namespace: str, table_name: str, role: str) -> bool:
    """True when enforcing RBAC on this table for this role would not change
    a single cell — no row filter, no column mask, no column denial.

    Callers use this to decide whether they can hand an Arrow table straight
    to the query backend instead of materialising a masked pandas copy.

    SAFETY CONTRACT — this function is allowed to return False when it is
    unsure, but must NEVER return True when a policy exists:

      * check_table_access() is still invoked here, so an unauthorised role
        raises TableAccessDenied on the fast path exactly as on the slow one.
      * Any error reaching the policy store returns False (fail closed), so
        a database blip degrades performance, never confidentiality.
    """
    check_table_access(namespace, table_name, role)

    try:
        for pol in get_role_policies(role):
            if pol["column_name"] == TABLE_DENY_SENTINEL:
                continue  # table-level grants/denies handled above
            if pol["namespace"] in (namespace, "*") and pol["table_name"] in (table_name, "*"):
                return False  # a mask or column deny applies

        for flt in get_row_filters(role):
            if flt["namespace"] in (namespace, "*") and flt["table_name"] in (table_name, "*"):
                return False  # a row filter applies
    except TableAccessDenied:
        raise
    except Exception:
        return False  # fail closed: unknown policy state -> take the slow path

    return True


