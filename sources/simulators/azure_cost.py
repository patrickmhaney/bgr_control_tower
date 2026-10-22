"""The Azure Cost Management daily export, in FOCUS format.

PRODUCTION SWAP
---------------
Read the export's CSV files from the `costs` container with dlt's filesystem
source instead of `rows_since()`. The export writes one file per day, so the
cursor on ChargePeriodStart carries over unchanged.
"""
from __future__ import annotations

import datetime as dt

import duckdb

from core.settings import settings


def rows_since(since: dt.date | None) -> list[dict]:
    con = duckdb.connect(settings.mock_db, read_only=True)
    try:
        sql = 'select * from azure_cost."focus_cost"'
        params: list = []
        if since is not None:
            sql += ' where "ChargePeriodStart" > ?'
            params.append(since)
        cur = con.execute(sql + ' order by "ChargePeriodStart", "ResourceName"', params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        con.close()
