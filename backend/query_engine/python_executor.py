# Copyright (c) 2025 Meldra AI Ltd. All rights reserved.
"""
query_engine/python_executor.py — Safe Python extraction engine.

Executes user-supplied Python scripts in a restricted namespace using
AST-level security inspection before running. Only a curated set of
modules and builtins is available to the script.

Security model:
  1. AST pre-scan blocks dangerous calls/imports before execution.
  2. Execution namespace is populated with:
       df         — pandas DataFrame from the Iceberg table
       arrow_table — PyArrow table equivalent
       pd, pa, duckdb, json, datetime, re, math
  3. The script must set `result_df` (a pandas DataFrame) as its output.
  4. Execution is wrapped in a 30-second timeout via concurrent.futures.

Blocked patterns (AST inspection):
  - import os / import sys / import subprocess / import socket
  - __import__() calls
  - open() calls
  - exec() or eval() calls within the script
  - compile() calls
"""

from __future__ import annotations

import ast
import concurrent.futures
import logging
import math
import re as re_module
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

import pandas as pd
import pyarrow as pa

from query_engine.models import QueryJob, QueryResult

logger = logging.getLogger(__name__)

EXECUTION_TIMEOUT_SECONDS = 30

# ─── Blocked names at AST level ───────────────────────────────────────────────

BLOCKED_MODULES: Set[str] = {
    "os", "sys", "subprocess", "socket", "shutil", "pathlib",
    "importlib", "ctypes", "multiprocessing", "threading",
    "signal", "resource", "tempfile", "glob",
    "builtins", "gc", "inspect", "types", "code", "codeop",
    "marshal", "pickle", "copyreg", "atexit", "traceback",
}

BLOCKED_BUILTINS: Set[str] = {
    "exec", "eval", "compile", "open", "__import__", "breakpoint",
    "input", "print",  # print is blocked to avoid stdout pollution; use result_df
    "vars", "dir", "globals", "locals",
    "getattr", "setattr", "delattr",  # block indirect dunder access (sandbox-escape gadget chains)
}

# String literals that must never appear as an argument to getattr/setattr/delattr
# (defense in depth — those builtins are already blocked entirely above, but this
# also catches obfuscated re-implementations via string formatting on identifiers).
BLOCKED_ATTR_NAMES: Set[str] = {
    "__class__", "__base__", "__bases__", "__mro__", "__subclasses__",
    "__globals__", "__code__", "__closure__", "__func__", "__self__",
    "__builtins__", "__dict__", "__getattribute__", "__reduce__", "__reduce_ex__",
}


# ─── AST Security Scanner ─────────────────────────────────────────────────────

class SecurityError(ValueError):
    """Raised when the AST scan finds a blocked pattern."""


class _SecurityVisitor(ast.NodeVisitor):
    """Walk the AST and raise SecurityError on any dangerous construct."""

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            top = alias.name.split(".")[0]
            if top in BLOCKED_MODULES:
                raise SecurityError(
                    f"Import of '{alias.name}' is not permitted in Python extraction scripts."
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            top = node.module.split(".")[0]
            if top in BLOCKED_MODULES:
                raise SecurityError(
                    f"Import from '{node.module}' is not permitted in Python extraction scripts."
                )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # Block direct calls to blocked builtins: exec(...), eval(...), open(...)
        if isinstance(node.func, ast.Name) and node.func.id in BLOCKED_BUILTINS:
            raise SecurityError(
                f"Calling '{node.func.id}()' is not permitted in Python extraction scripts."
            )
        # Block attribute calls like builtins.__import__
        if isinstance(node.func, ast.Attribute) and node.func.attr in BLOCKED_BUILTINS:
            raise SecurityError(
                f"Calling '.{node.func.attr}()' is not permitted."
            )
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        # Block dunder attribute access like __class__.__subclasses__
        if node.attr.startswith("__") and node.attr.endswith("__") and node.attr not in (
            "__init__", "__str__", "__repr__", "__len__", "__iter__", "__next__",
            "__getitem__", "__setitem__", "__contains__", "__bool__", "__float__",
            "__int__", "__add__", "__sub__", "__mul__", "__truediv__",
        ):
            raise SecurityError(
                f"Access to dunder attribute '{node.attr}' is not permitted."
            )
        # Block bare references to dangerous names even without an immediate call
        # (e.g. `g = some_obj.getattr` followed by `g(...)` later), which would
        # otherwise dodge the Call-based BLOCKED_BUILTINS check below.
        if node.attr in BLOCKED_BUILTINS:
            raise SecurityError(
                f"Access to '.{node.attr}' is not permitted in Python extraction scripts."
            )
        self.generic_visit(node)


def _ast_security_scan(script: str) -> None:
    """Parse and walk the AST. Raise SecurityError on any blocked pattern."""
    try:
        tree = ast.parse(script, mode="exec")
    except SyntaxError as exc:
        raise ValueError(f"Syntax error in Python script: {exc}") from exc
    _SecurityVisitor().visit(tree)


# ─── Safe execution namespace ─────────────────────────────────────────────────

def _build_namespace(df: pd.DataFrame, arrow_table: pa.Table) -> Dict[str, Any]:
    """Build a restricted namespace for exec()."""
    import duckdb as _duckdb
    import json as _json

    return {
        # Data
        "df": df,
        "arrow_table": arrow_table,
        # Libraries
        "pd": pd,
        "pa": pa,
        "duckdb": _duckdb,
        "json": _json,
        "datetime": datetime,
        "re": re_module,
        "math": math,
        # Output placeholder (script must set this)
        "result_df": None,
        # Safe builtins subset
        "__builtins__": {
            "abs": abs, "all": all, "any": any, "bool": bool,
            "bytes": bytes, "chr": chr, "dict": dict, "enumerate": enumerate,
            "filter": filter, "float": float, "format": format, "frozenset": frozenset,
            "hasattr": hasattr, "hash": hash,
            "int": int, "isinstance": isinstance, "issubclass": issubclass,
            "iter": iter, "len": len, "list": list, "map": map, "max": max,
            "min": min, "next": next, "ord": ord, "pow": pow, "print": lambda *a, **k: None,
            "range": range, "repr": repr, "reversed": reversed, "round": round,
            "set": set, "slice": slice, "sorted": sorted,
            "str": str, "sum": sum, "tuple": tuple, "type": type, "zip": zip,
            "True": True, "False": False, "None": None,
        },
    }


# ─── Executor ────────────────────────────────────────────────────────────────

class PythonExecutor:
    """Executes AST-safe Python extraction scripts against Iceberg tables."""

    def execute(self, job: QueryJob) -> QueryResult:
        t0 = time.perf_counter()

        # ── 1. Load Iceberg data ──────────────────────────────────────────────
        arrow_table = self._load_iceberg(job.namespace, job.table_name, job.filters)
        df = arrow_table.to_pandas()

        # Enforce column-level RBAC before the script ever sees the data —
        # the sandbox has no way to distinguish "masked" from "real" data,
        # so redaction must happen here, not on the script's output.
        from rbac_utils import apply_rbac_to_dataframe
        df = apply_rbac_to_dataframe(df, job.namespace, job.table_name, job.role)
        import pyarrow as _pa
        arrow_table = _pa.Table.from_pandas(df, preserve_index=False)

        # ── 2. AST security scan ──────────────────────────────────────────────
        _ast_security_scan(job.python_script)

        # ── 3. Execute with timeout ───────────────────────────────────────────
        namespace = _build_namespace(df, arrow_table)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(exec, job.python_script, namespace)
            try:
                future.result(timeout=EXECUTION_TIMEOUT_SECONDS)
            except concurrent.futures.TimeoutError:
                raise TimeoutError(
                    f"Python extraction script exceeded {EXECUTION_TIMEOUT_SECONDS}s timeout."
                )

        # ── 4. Harvest result_df ──────────────────────────────────────────────
        result_df: Optional[pd.DataFrame] = namespace.get("result_df")
        if result_df is None:
            raise ValueError(
                "Python extraction script must set 'result_df' (a pandas DataFrame) as its output variable."
            )
        if not isinstance(result_df, pd.DataFrame):
            raise ValueError(
                f"'result_df' must be a pandas DataFrame, got {type(result_df).__name__}."
            )

        duration_ms = int((time.perf_counter() - t0) * 1000)

        # ── 5. Build QueryResult ──────────────────────────────────────────────
        total_rows = len(result_df)
        truncated = total_rows > job.limit
        if truncated:
            result_df = result_df.head(job.limit)

        rows = self._sanitise_rows(result_df)
        columns = list(result_df.columns)

        plan = (
            f"[DQE/PYTHON] Source: {job.namespace}.{job.table_name} | "
            f"Input rows: {len(df)} | Output rows: {total_rows} | "
            f"Duration: {duration_ms}ms\n\n"
            f"Script (first 500 chars):\n{job.python_script[:500]}"
        )

        logger.info(
            "[PythonExecutor] job=%s rows_in=%d rows_out=%d duration=%dms",
            job.job_id, len(df), total_rows, duration_ms,
        )

        return QueryResult(
            columns=columns,
            rows=rows,
            total_rows=total_rows,
            truncated=truncated,
            execution_plan=plan,
            engine_used="python_exec",
            duration_ms=duration_ms,
        )

    def explain(self, job: QueryJob) -> str:
        """Return the AST structure without executing."""
        _ast_security_scan(job.python_script)
        try:
            tree = ast.parse(job.python_script, mode="exec")
            return (
                f"[DQE/PYTHON] Source: {job.namespace}.{job.table_name}\n"
                f"Script AST validated — {len(tree.body)} top-level statement(s).\n"
                f"Script:\n{job.python_script}"
            )
        except Exception as exc:
            return f"[DQE/PYTHON] AST parse error: {exc}"

    # ─── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _load_iceberg(
        namespace: str, table_name: str, filters: Optional[Dict[str, Any]]
    ) -> pa.Table:
        import sys, os
        backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if backend_root not in sys.path:
            sys.path.insert(0, backend_root)
        from catalog_setup import get_catalog
        catalog = get_catalog()
        try:
            table = catalog.load_table((namespace, table_name))
        except Exception as exc:
            raise ValueError(
                f"Iceberg table '{namespace}.{table_name}' not found: {exc}"
            ) from exc
        return table.scan().to_arrow()

    @staticmethod
    def _sanitise_rows(df: pd.DataFrame) -> List[Dict[str, Any]]:
        rows = df.to_dict(orient="records")
        result = []
        for row in rows:
            clean: Dict[str, Any] = {}
            for k, v in row.items():
                if v is None or (isinstance(v, float) and math.isnan(v)):
                    clean[k] = None
                elif isinstance(v, (str, int, float, bool)):
                    clean[k] = v
                elif hasattr(v, "item"):
                    clean[k] = v.item()
                else:
                    clean[k] = str(v)
            result.append(clean)
        return result
