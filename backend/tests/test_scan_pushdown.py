# Copyright (c) 2025-2026 Meldra AI Ltd. All rights reserved.
"""
tests/test_scan_pushdown.py — Verification for SQL scan pushdown and column projection.
"""

import pytest
from query_engine.sql_pushdown import (
    extract_projection_from_sql,
    extract_where_predicates,
    build_iceberg_row_filter,
)


def test_extract_projection_simple():
    sql = "SELECT mpan, kwh, reading_ts FROM iceberg_table WHERE region = 'NW'"
    cols = extract_projection_from_sql(sql)
    assert cols == ["mpan", "kwh", "reading_ts"]


def test_extract_projection_star():
    sql = "SELECT * FROM iceberg_table WHERE region = 'NW'"
    cols = extract_projection_from_sql(sql)
    assert cols is None


def test_extract_where_binary_predicates():
    sql = "SELECT mpan FROM iceberg_table WHERE region = 'NW' AND status = 'ACTIVE' AND reading_val >= 100"
    preds = extract_where_predicates(sql)
    assert len(preds) == 3
    assert ("region", "=", "NW") in preds
    assert ("status", "=", "ACTIVE") in preds
    assert ("reading_val", ">=", 100) in preds


def test_extract_where_in_and_null():
    sql = "SELECT id FROM t WHERE status IN ('OPEN', 'PENDING') AND error_code IS NULL"
    preds = extract_where_predicates(sql)
    assert len(preds) == 2
    assert ("status", "IN", ("OPEN", "PENDING")) in preds
    assert ("error_code", "IS NULL", None) in preds


def test_build_iceberg_row_filter():
    sql = "SELECT mpan FROM iceberg_table WHERE region = 'NW' AND status = 'ACTIVE'"
    expr, descriptions = build_iceberg_row_filter(sql=sql)
    assert len(descriptions) == 2
    assert any("region = 'NW'" in d for d in descriptions)
    assert any("status = 'ACTIVE'" in d for d in descriptions)
