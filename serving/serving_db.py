"""Read the marts from the serving database (Postgres in Azure, DuckDB locally)."""
from __future__ import annotations

import datetime as dt
import decimal
import os
import re

from core.settings import settings

SCHEMA = "marts"
NAME = re.compile(r"^[a-z][a-z0-9_]*$")


def _clean(v):
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    return v


def _connect():
    if settings.serving_destination == "postgres":
        import psycopg2

        url = settings.serving_url
        return psycopg2.connect(url, password=os.environ.get("CT_SERVING_PASSWORD") or None)
    import duckdb

    return duckdb.connect(settings.serving_url, read_only=True)


def list_datasets() -> list[str]:
    con = _connect()
    try:
        cur = con.cursor()
        cur.execute("select table_name from information_schema.tables where table_schema = %s "
                    "and table_name not like '\\_dlt%%' order by 1"
                    if settings.serving_destination == "postgres" else
                    "select table_name from information_schema.tables where table_schema = ? "
                    "and table_name not like '\\_dlt%' escape '\\' order by 1", [SCHEMA])
        return [r[0] for r in cur.fetchall()]
    finally:
        con.close()


def read_dataset(name: str, limit: int = 1000, offset: int = 0) -> dict:
    if not NAME.match(name) or name not in list_datasets():
        raise KeyError(name)
    con = _connect()
    try:
        cur = con.cursor()
        cur.execute(f'select * from {SCHEMA}."{name}" limit {int(limit)} offset {int(offset)}')
        cols = [d[0] for d in cur.description if not d[0].startswith("_dlt")]
        keep = [i for i, d in enumerate(cur.description) if not d[0].startswith("_dlt")]
        rows = [[_clean(r[i]) for i in keep] for r in cur.fetchall()]
        return {"dataset": name, "columns": cols, "rows": rows, "limit": limit, "offset": offset}
    finally:
        con.close()
