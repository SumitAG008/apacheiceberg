# Copyright (c) 2025 Meldra AI Ltd. All rights reserved.
"""
rbac_utils.py — Column-level RBAC enforcement applied at the data layer.

Masking/denial is applied to the source DataFrame *before* it is registered
with DuckDB (or handed to the Python extraction sandbox), so aliasing a
column, wrapping it in a subquery, or renaming it in the SELECT list cannot
bypass the policy — the underlying value is already redacted or the column
is already gone by the time any SQL or script can reference it.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd


def get_role_policies(role: str) -> List[Dict[str, Any]]:
    """Fetch all RBAC policies configured for a given role."""
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
    or to '*' (wildcard, applies to every table for that role).
    """
    policies = get_role_policies(role)
    if not policies:
        return df

    df = df.copy()
    for pol in policies:
        tbl_scope = pol["table_name"]
        if tbl_scope not in (table_name, "*"):
            continue
        col = pol["column_name"]
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
        if p["action"] == "deny" and p["table_name"] in (table_name, "*")
    ]
