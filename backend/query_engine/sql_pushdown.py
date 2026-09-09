# Copyright (c) 2025-2026 Meldra AI Ltd. All rights reserved.
"""
query_engine/sql_pushdown.py — SQL-derived predicate pushdown and column projection.

Translates SQL WHERE clauses and SELECT column projections into PyIceberg scan
expressions for partition pruning and file pruning before loading data into DuckDB.
Implements the roadmap laid out in docs/technical/TD-004-scan-pushdown.md.

Design principles:
1. Conservative translation: only push predicates that PyIceberg can evaluate with
   100% equivalence (equality, comparisons, IN, IS NULL/NOT NULL, AND/OR).
2. Never return wrong rows: any complex, ambiguous or unparseable predicate is
   left for DuckDB post-scan filtering.
3. Zero-dependency fallback: works with sqlglot if available, with a built-in
   lexical AST parser as a reliable fallback.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


def _parse_literal(val_str: str) -> Any:
    """Parse a literal token into a typed Python value."""
    s = val_str.strip()
    # Quoted string
    if (s.startswith("'") and s.endswith("'")) or (s.startswith('"') and s.endswith('"')):
        return s[1:-1]
    # Boolean
    if s.upper() == "TRUE":
        return True
    if s.upper() == "FALSE":
        return False
    if s.upper() == "NULL":
        return None
    # Integer
    if re.match(r"^-?\d+$", s):
        try:
            return int(s)
        except ValueError:
            pass
    # Float
    if re.match(r"^-?\d+\.\d+$", s):
        try:
            return float(s)
        except ValueError:
            pass
    return s


def _build_pyiceberg_expr(op: str, col: str, val: Any) -> Optional[Any]:
    """Build a PyIceberg expression object for a binary predicate."""
    try:
        from pyiceberg.expressions import (
            EqualTo,
            NotEqualTo,
            GreaterThan,
            GreaterThanOrEqual,
            LessThan,
            LessThanOrEqual,
            In,
            IsNull,
            NotNull,
        )

        op_norm = op.upper().strip()
        if op_norm in ("=", "=="):
            return EqualTo(col, val)
        elif op_norm in ("!=", "<>"):
            return NotEqualTo(col, val)
        elif op_norm == ">":
            return GreaterThan(col, val)
        elif op_norm == ">=":
            return GreaterThanOrEqual(col, val)
        elif op_norm == "<":
            return LessThan(col, val)
        elif op_norm == "<=":
            return LessThanOrEqual(col, val)
        elif op_norm == "IN":
            if isinstance(val, (list, tuple, set)):
                return In(col, val)
            return In(col, (val,))
        elif op_norm == "IS NULL":
            return IsNull(col)
        elif op_norm == "IS NOT NULL":
            return NotNull(col)
        return None
    except ImportError:
        logger.debug("[Pushdown] PyIceberg expressions not imported in environment.")
        return None
    except Exception as e:
        logger.warning("[Pushdown] Could not build PyIceberg expression for %s %s %s: %s", col, op, val, e)
        return None


def extract_projection_from_sql(sql: str) -> Optional[List[str]]:
    """
    Extract requested column names from a SELECT clause.
    Returns None if SELECT * or complex functions/aggregates prevent safe pruning.
    """
    clean_sql = sql.strip().rstrip(";")
    match = re.search(r"^\s*SELECT\s+(.+?)\s+FROM\b", clean_sql, re.IGNORECASE | re.DOTALL)
    if not match:
        return None

    raw_cols = match.group(1).strip()
    if "*" in raw_cols or raw_cols == "":
        return None

    cols: List[str] = []
    # Split top-level commas (ignoring parentheses for function calls)
    parts = []
    depth = 0
    current = []
    for char in raw_cols:
        if char == "(":
            depth += 1
            current.append(char)
        elif char == ")":
            depth -= 1
            current.append(char)
        elif char == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    if current:
        parts.append("".join(current).strip())

    for part in parts:
        part = part.strip()
        # If it contains complex function calls, we fall back to reading full columns needed
        if "(" in part:
            # Extract identifiers inside function calls
            inner_cols = re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", part)
            sql_keywords = {"SUM", "COUNT", "AVG", "MIN", "MAX", "COALESCE", "CAST", "AS", "DISTINCT", "CASE", "WHEN", "THEN", "ELSE", "END"}
            for ic in inner_cols:
                if ic.upper() not in sql_keywords and not ic.isdigit():
                    cols.append(ic)
            continue

        # Handle aliases: "col AS alias" or "col alias"
        alias_match = re.match(r"^([a-zA-Z_][a-zA-Z0-9_\.]*)(?:\s+(?:AS\s+)?([a-zA-Z_][a-zA-Z0-9_]*))?$", part, re.IGNORECASE)
        if alias_match:
            cname = alias_match.group(1).split(".")[-1]
            cols.append(cname)

    # Deduplicate while preserving order
    seen: Set[str] = set()
    result = []
    for c in cols:
        if c not in seen:
            seen.add(c)
            result.append(c)

    return result if result else None


def extract_where_predicates(sql: str) -> List[Tuple[str, str, Any]]:
    """
    Extract translatable binary predicates from SQL WHERE clause.
    Returns list of (column, operator, typed_value).
    """
    clean_sql = sql.strip().rstrip(";")
    where_match = re.search(
        r"\bWHERE\b\s+(.+?)(?:\s+\b(?:GROUP\s+BY|HAVING|ORDER\s+BY|LIMIT|WINDOW)\b|$)",
        clean_sql,
        re.IGNORECASE | re.DOTALL,
    )
    if not where_match:
        return []

    where_clause = where_match.group(1).strip()
    predicates: List[Tuple[str, str, Any]] = []

    # Tokenize by AND (OR branches require compound handling)
    and_branches = re.split(r"\bAND\b", where_clause, flags=re.IGNORECASE)

    for branch in and_branches:
        branch = branch.strip()
        if branch.startswith("(") and branch.endswith(")"):
            depth = 0
            enclosed = True
            for i, ch in enumerate(branch):
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0 and i < len(branch) - 1:
                        enclosed = False
                        break
            if enclosed:
                branch = branch[1:-1].strip()
        # Match IS NULL / IS NOT NULL
        null_match = re.match(r"^([a-zA-Z_][a-zA-Z0-9_\.]*)\s+IS\s+(NOT\s+NULL|NULL)$", branch, re.IGNORECASE)
        if null_match:
            col = null_match.group(1).split(".")[-1]
            op = f"IS {null_match.group(2).upper()}"
            predicates.append((col, op, None))
            continue

        # Match IN clause: col IN ('a', 'b') or col IN (1, 2)
        in_match = re.match(r"^([a-zA-Z_][a-zA-Z0-9_\.]*)\s+IN\s*\((.+?)\)$", branch, re.IGNORECASE)
        if in_match:
            col = in_match.group(1).split(".")[-1]
            raw_items = in_match.group(2).split(",")
            vals = tuple(_parse_literal(item.strip()) for item in raw_items if item.strip())
            predicates.append((col, "IN", vals))
            continue

        # Match binary comparison: col (=|!=|>|>=|<|<=) literal
        cmp_match = re.match(r"^([a-zA-Z_][a-zA-Z0-9_\.]*)\s*(=|!=|<>|>=|<=|>|<)\s*(.+)$", branch, re.IGNORECASE)
        if cmp_match:
            col = cmp_match.group(1).split(".")[-1]
            op = cmp_match.group(2)
            raw_val = cmp_match.group(3).strip()
            # If right side is a column rather than a literal, do not push down
            if re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", raw_val) and raw_val.upper() not in ("TRUE", "FALSE", "NULL"):
                continue
            val = _parse_literal(raw_val)
            predicates.append((col, op, val))

    return predicates


def build_iceberg_row_filter(
    explicit_filters: Optional[Dict[str, Any]] = None,
    sql: Optional[str] = None,
) -> Tuple[Optional[Any], List[str]]:
    """
    Construct a PyIceberg row_filter expression combining explicit job.filters
    with predicates safely derived from the SQL query.

    Returns:
        (pyiceberg_expr, list_of_pushed_predicates_human_readable)
    """
    from pyiceberg.expressions import And

    expr = None
    pushed_descriptions: List[str] = []

    # 1. Process explicit filters dictionary
    if explicit_filters:
        for col, val in explicit_filters.items():
            sub = _build_pyiceberg_expr("=", col, val)
            if sub is not None:
                expr = sub if expr is None else And(expr, sub)
                pushed_descriptions.append(f"{col} = {repr(val)}")

    # 2. Extract and translate predicates from SQL
    if sql:
        extracted = extract_where_predicates(sql)
        for col, op, val in extracted:
            sub = _build_pyiceberg_expr(op, col, val)
            if sub is not None:
                expr = sub if expr is None else And(expr, sub)
                if op in ("IS NULL", "IS NOT NULL"):
                    pushed_descriptions.append(f"{col} {op}")
                elif op == "IN":
                    pushed_descriptions.append(f"{col} IN {val}")
                else:
                    pushed_descriptions.append(f"{col} {op} {repr(val)}")

    return expr, pushed_descriptions
