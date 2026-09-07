"""Shared read-only handle on the mock source database."""
from __future__ import annotations

import os
import threading

import duckdb

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MOCK_DB = os.path.join(ROOT, "mock_sources.duckdb")

_local = threading.local()


def connection() -> duckdb.DuckDBPyConnection:
    if getattr(_local, "con", None) is None:
        _local.con = duckdb.connect(MOCK_DB, read_only=True)
    return _local.con


def rows(sql: str, params: list | None = None) -> list[dict]:
    """Run a query and return plain dicts, the way a driver or an API would."""
    result = connection().execute(sql, params or [])
    columns = [d[0] for d in result.description]
    return [dict(zip(columns, row)) for row in result.fetchall()]
