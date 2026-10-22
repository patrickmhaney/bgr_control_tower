"""Sage X3, read as a SQL Server database with change data capture enabled.

PRODUCTION SWAP
---------------
Point `_rows` at a pymssql or pyodbc connection to a read replica of the
production folder and replace the four queries with their SQL Server forms:

    snapshot   SELECT <columns> FROM <folder>.<TABLE>   (inside a snapshot-isolation
               transaction, reading sys.fn_cdc_get_max_lsn() first)
    changes    SELECT * FROM cdc.fn_cdc_get_all_changes_dbo_<TABLE>(@from, @to, 'all')
    max_lsn    SELECT sys.fn_cdc_get_max_lsn()
    min_lsn    SELECT sys.fn_cdc_get_min_lsn('dbo_<TABLE>')

LSNs are binary(10) in SQL Server; here they are the same ten bytes as
twenty hex characters, which sort the same way.

Columns are always enumerated, never `SELECT *`: a `SELECT *` against X3 pulls
hundreds of columns and breaks silently when Sage adds one in an upgrade.
"""
from __future__ import annotations

import duckdb

from core.settings import settings

SCHEMA = "sage_x3"
CDC_META = ("__$start_lsn", "__$seqval", "__$operation", "__$update_mask")


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _rows(sql: str, params: list | None = None) -> list[dict]:
    con = duckdb.connect(settings.mock_db, read_only=True)
    try:
        cur = con.execute(sql, params or [])
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        con.close()


def columns(table: str) -> list[str]:
    return [r["column_name"] for r in _rows(
        "select column_name from duckdb_columns() where schema_name = ? and table_name = ? "
        "order by column_index", [SCHEMA, table])]


def max_lsn() -> str:
    """The highest LSN written so far, as twenty hex characters."""
    rows = _rows("select next_lsn - 1 as lsn from clock.state")
    return f"{rows[0]['lsn']:020X}"


def min_lsn() -> str:
    """The lowest LSN still readable. Anything below it has been purged."""
    rows = _rows("select low_water_lsn + 1 as lsn from clock.state")
    return f"{rows[0]['lsn']:020X}"


def snapshot(table: str) -> tuple[list[dict], str]:
    """Every row of the table, and the LSN the snapshot is consistent with."""
    lsn = max_lsn()
    cols = ", ".join(_q(c) for c in columns(table))
    return _rows(f"select {cols} from {SCHEMA}.{_q(table)}"), lsn


def changes(table: str, after_lsn: str, up_to_lsn: str) -> list[dict]:
    """Change rows with after_lsn < LSN <= up_to_lsn, in commit order."""
    data_cols = ", ".join(_q(c) for c in columns(table))
    meta = ", ".join(_q(c) for c in CDC_META)
    return _rows(
        f"select {meta}, {data_cols} from cdc.{_q('dbo_' + table + '_CT')} "
        f"where \"__$start_lsn\" > ? and \"__$start_lsn\" <= ? "
        f"order by \"__$start_lsn\", \"__$seqval\"",
        [after_lsn, up_to_lsn])
