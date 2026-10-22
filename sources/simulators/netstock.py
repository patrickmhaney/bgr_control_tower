"""Netstock, read as a snapshot API.

PRODUCTION SWAP
---------------
Replace `fetch()` and `sync_timestamp()` with the real endpoints. The design
around them - replace semantics, skip when the sync has not moved, freshness
carried through - is right whatever the API turns out to look like.
"""
from __future__ import annotations

import duckdb

from core.settings import settings

SCHEMA = "netstock"


def _rows(sql: str) -> list[dict]:
    con = duckdb.connect(settings.mock_db, read_only=True)
    try:
        cur = con.execute(sql)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        con.close()


def sync_timestamp():
    return _rows(f'select max(last_sync_at) as ts from {SCHEMA}."item_location"')[0]["ts"]


def fetch(dataset: str) -> list[dict]:
    """One call, the whole dataset. No paging, no cursor, no filter."""
    return _rows(f'select * from {SCHEMA}."{dataset}"')
