"""A freight platform's REST API (a TMS or freight-audit service): carriers,
shipments and carrier invoices, each listed with an updated-since filter.

PRODUCTION SWAP
---------------
Call the platform's list endpoints (`GET /carriers`, `/shipments`,
`/invoices?updated_since=...`) instead of reading the mock database. The
cursor on `updated_at` and the shipment's `reference` (the ERP delivery
number, as the carrier keyed it) carry over unchanged.
"""
from __future__ import annotations

import datetime as dt

import duckdb

from core.settings import settings


def list_rows(table: str, updated_since: dt.date | None = None) -> list[dict]:
    con = duckdb.connect(settings.mock_db, read_only=True)
    try:
        sql, params = f'select * from freight."{table}"', []
        if updated_since is not None:
            sql += ' where "updated_at" >= ?'
            params.append(updated_since)
        cur = con.execute(sql + " order by 1", params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        con.close()
