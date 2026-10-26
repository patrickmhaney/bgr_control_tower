"""The clock: put the synthetic sources in the state of any day, one day at a time.

    python -m sources.clock init                 # the sources as of INITIAL_DATE
    python -m sources.clock advance --days 3     # three more days of business
    python -m sources.clock status

The mock database (`.data/mock_sources.duckdb` locally) holds what each source
system shows today:

    sage_x3, hubspot, netstock, azure_cost   the systems' current tables
    freight                                  when the project's scenario has one
    cdc                                      SQL Server-style change tables for
                                             every X3 table, written by advance
    truth                                    the answer key for MDM; nothing in
                                             the pipeline reads it
    clock                                    today's date and the LSN counters

Advancing a day computes the new state from the deterministic timeline,
diffs it against the current tables, and appends the difference to
`cdc.dbo_<TABLE>_CT` the way SQL Server change data capture would: operation
1 delete, 2 insert, 3 update before-image, 4 update after-image, ordered by
`__$start_lsn` and `__$seqval`. Change rows older than the retention window
are purged on every advance, exactly the trap the ingestion has to survive.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import os
import pickle
from contextlib import contextmanager

import duckdb
import pyarrow as pa

from core.settings import settings

from . import generate as g

X3_KEYS: dict[str, tuple[str, ...]] = {
    "COMPANY": ("CPY_0",),
    "FACILITY": ("FCY_0",),
    "APLSTD": ("CHAPTER_0", "CODE_0", "LANNUM_0"),
    "ATEXTRA": ("CODFIC_0", "ZONE_0", "LANNUM_0", "IDENT1_0", "IDENT2_0"),
    "AUTILIS": ("USR_0",),
    "REPRESENT": ("REPNUM_0",),
    "BPARTNER": ("BPRNUM_0",),
    "BPCUSTOMER": ("BPCNUM_0",),
    "BPSUPPLIER": ("BPSNUM_0",),
    "BPADDRESS": ("BPANUM_0", "BPAADD_0"),
    "ITMMASTER": ("ITMREF_0",),
    "ITMFACILIT": ("ITMREF_0", "STOFCY_0"),
    "STOCK": ("STOFCY_0", "ITMREF_0", "LOT_0", "LOC_0"),
    "STOJOU": ("ROWID",),
    "SORDER": ("SOHNUM_0",),
    "SORDERQ": ("SOHNUM_0", "SOPLIN_0"),
    "SORDERP": ("SOHNUM_0", "SOPLIN_0"),
    "SDELIVERY": ("SDHNUM_0",),
    "SDELIVERYD": ("SDHNUM_0", "SDDLIN_0"),
    "SINVOICEV": ("NUM_0",),
    "SINVOICED": ("NUM_0", "SIDLIN_0"),
    "SRETURN": ("SRHNUM_0",),
    "SRETURND": ("SRHNUM_0", "SRDLIN_0"),
    "PORDER": ("POHNUM_0",),
    "PORDERQ": ("POHNUM_0", "POPLIN_0"),
    "PRECEIPT": ("PTHNUM_0",),
    "PRECEIPTD": ("PTHNUM_0", "PTDLIN_0"),
    "PINVOICE": ("NUM_0",),
    "PINVOICED": ("NUM_0", "PIDLIN_0"),
    "GACCENTRY": ("NUM_0",),
    "GACCENTRYD": ("NUM_0", "LIN_0"),
    "STOCOUNT": ("SESNUM_0",),
    "STOCOUNTD": ("SESNUM_0", "CNTLIN_0"),
}

#: SQL Server's default CDC retention is 4320 minutes.
RETENTION_DAYS = 3

LSN_WIDTH = 20  # binary(10) as hex


def lsn_hex(n: int) -> str:
    return f"{n:0{LSN_WIDTH}X}"


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


# ---------------------------------------------------------------------------
# Timeline cache and column types
# ---------------------------------------------------------------------------
def _cache_path() -> str:
    return os.path.join(settings.data_dir, "timeline.pkl")


def load_timeline() -> tuple[g.Timeline, dict]:
    """The timeline plus a fixed column schema per table.

    The schema is inferred once from the full timeline, so a column that is
    empty on some particular day keeps its type and the CDC diff compares like
    with like.
    """
    g._apply(g.load_scenario())                  # the project in use, even from the cache
    path = _cache_path()
    if os.path.exists(path):
        with open(path, "rb") as fh:
            cached = pickle.load(fh)
        if cached.get("version") == _source_version():
            return cached["timeline"], cached["schemas"]
    timeline = g.build_timeline()
    full = g.state_as_of(timeline, g.TIMELINE_END)
    schemas = {}
    for schema in ("sage_x3", "hubspot"):
        tables = getattr(timeline, "x3" if schema == "sage_x3" else "hs")
        schemas[schema] = {t: _infer_schema(rows) for t, rows in tables.items()}
    for schema in full:
        if schema not in ("sage_x3", "hubspot"):
            schemas[schema] = {t: _infer_schema(rows) for t, rows in full[schema].items()}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        pickle.dump({"version": _source_version(), "timeline": timeline, "schemas": schemas}, fh)
    return timeline, schemas


def _source_version() -> str:
    """Invalidate the cache whenever the generator or the project's scenario changes."""
    from core import project

    digest = hashlib.sha256()
    for path in (g.__file__, project.current().scenario):
        with open(path, "rb") as fh:
            digest.update(fh.read())
    return digest.hexdigest()


def _infer_schema(rows: list[dict]) -> pa.Schema:
    columns: dict[str, pa.DataType] = {}
    order: list[str] = []
    for row in rows:
        for k, v in row.items():
            if k not in columns:
                order.append(k)
                columns[k] = pa.null()
            current = columns[k]
            if v is None:
                continue
            if isinstance(v, bool):
                t = pa.bool_()
            elif isinstance(v, int):
                t = pa.int64()
            elif isinstance(v, float):
                t = pa.float64()
            elif isinstance(v, dt.date):
                t = pa.date32()
            else:
                t = pa.string()
            if current == pa.null() or (current == pa.int64() and t == pa.float64()):
                columns[k] = t
    return pa.schema([(k, columns[k] if columns[k] != pa.null() else pa.string()) for k in order])


def _arrow(rows: list[dict], schema: pa.Schema) -> pa.Table:
    return pa.Table.from_pylist(rows, schema=schema)


# ---------------------------------------------------------------------------
# Database access
# ---------------------------------------------------------------------------
@contextmanager
def connect(read_only: bool = False):
    con = duckdb.connect(settings.mock_db, read_only=read_only)
    try:
        yield con
    finally:
        con.close()


def _write_table(con, schema: str, table: str, data: pa.Table) -> None:
    con.register("_incoming", data)
    con.execute(f"create or replace table {schema}.{_q(table)} as select * from _incoming")
    con.unregister("_incoming")


def _clock(con) -> dict:
    row = con.execute("select today, next_lsn, low_water_lsn from clock.state").fetchone()
    return {"today": row[0], "next_lsn": row[1], "low_water_lsn": row[2]}


def init(as_of: dt.date | None = None) -> None:
    """Rebuild the mock database as of `as_of` (default the scenario's initial date),
    with CDC enabled and empty."""
    timeline, schemas = load_timeline()
    as_of = as_of or g.INITIAL_DATE
    state = g.state_as_of(timeline, as_of)
    os.makedirs(os.path.dirname(settings.mock_db), exist_ok=True)
    if os.path.exists(settings.mock_db):
        os.remove(settings.mock_db)
    with connect() as con:
        for schema, tables in state.items():
            con.execute(f"create schema {schema}")
            for table, rows in tables.items():
                _write_table(con, schema, table, _arrow(rows, schemas[schema][table]))
        con.execute("create schema truth")
        for table, rows in timeline.truth.items():
            _write_table(con, "truth", table, pa.Table.from_pylist(rows))
        con.execute("create schema cdc")
        for table in X3_KEYS:
            con.execute(f"""
                create table cdc.{_q('dbo_' + table + '_CT')} as
                select ''::varchar as "__$start_lsn", ''::varchar as "__$seqval",
                       0::integer as "__$operation", null::varchar as "__$update_mask", *
                from sage_x3.{_q(table)} where false
            """)
        con.execute("""create table cdc.lsn_time_mapping (
                           start_lsn varchar, tran_begin_time timestamp, tran_end_time timestamp)""")
        con.execute("create schema clock")
        # LSN 1 marks the moment CDC was enabled. Nothing at or below the low
        # water mark can be read from the change tables.
        con.execute("create table clock.state as select ?::date as today, 2::bigint as next_lsn, "
                    "1::bigint as low_water_lsn, ?::integer as retention_days",
                    [as_of, RETENTION_DAYS])


def advance(days: int = 1) -> list[tuple[dt.date, int]]:
    """Move the sources forward `days` days. Returns (day, change rows) pairs."""
    timeline, schemas = load_timeline()
    out = []
    with connect() as con:
        for _ in range(days):
            clk = _clock(con)
            day = clk["today"] + dt.timedelta(days=1)
            if day > g.TIMELINE_END:
                raise SystemExit(f"The timeline ends on {g.TIMELINE_END}; cannot advance past it.")
            state = g.state_as_of(timeline, day)
            next_lsn = clk["next_lsn"]
            n_changes = 0
            for i, table in enumerate(X3_KEYS):
                data = _arrow(state["sage_x3"][table], schemas["sage_x3"][table])
                tran_time = dt.datetime.combine(day, dt.time(22, 0)) + dt.timedelta(minutes=i)
                n = _capture(con, table, data, lsn_hex(next_lsn), tran_time)
                if n:
                    next_lsn += 1
                    n_changes += n
                _write_table(con, "sage_x3", table, data)
            for schema in state:
                if schema == "sage_x3":
                    continue
                for table, rows in state[schema].items():
                    _write_table(con, schema, table, _arrow(rows, schemas[schema][table]))
            low_water = _cleanup(con, day, clk["low_water_lsn"])
            con.execute("update clock.state set today = ?, next_lsn = ?, low_water_lsn = ?",
                        [day, next_lsn, low_water])
            out.append((day, n_changes))
    return out


def _capture(con, table: str, new: pa.Table, lsn: str, tran_time: dt.datetime) -> int:
    """Diff today's table against yesterday's and append CDC rows. Returns the row count."""
    keys = X3_KEYS[table]
    old = f"sage_x3.{_q(table)}"
    ct = f"cdc.{_q('dbo_' + table + '_CT')}"
    on = " and ".join(f"n.{_q(k)} is not distinct from o.{_q(k)}" for k in keys)
    con.register("_new", new)
    con.execute(f"""
        create or replace temp table _changed as
        select * from _new except select * from {old}
    """)
    con.execute(f"""
        create or replace temp table _deleted as
        select o.* from {old} o where not exists (select 1 from _new n where {on})
    """)
    con.execute(f"""
        create or replace temp table _changes as
        select 1 as op, 0 as part, o.* from _deleted o
        union all
        select 3, 1, o.* from {old} o where exists (select 1 from _changed n where {on})
        union all
        select case when exists (select 1 from {old} o where {on}) then 4 else 2 end,
               case when exists (select 1 from {old} o where {on}) then 2 else 3 end, n.*
        from _changed n
    """)
    order_keys = ", ".join(_q(k) for k in keys)
    n = con.execute("select count(*) from _changes").fetchone()[0]
    if n:
        cols = ", ".join(_q(c) for c in new.column_names)
        con.execute(f"""
            insert into {ct}
            select ? as "__$start_lsn",
                   lpad(upper(to_hex(row_number() over (
                       order by case part when 0 then 0 when 3 then 2 else 1 end,
                                {order_keys}, part))),
                        {LSN_WIDTH}, '0') as "__$seqval",
                   op as "__$operation", null as "__$update_mask", {cols}
            from _changes
        """, [lsn])
        con.execute("insert into cdc.lsn_time_mapping values (?, ?, ?)",
                    [lsn, tran_time, tran_time + dt.timedelta(seconds=1)])
    con.unregister("_new")
    return n


def _cleanup(con, today: dt.date, low_water: int) -> int:
    """Purge change rows older than the retention window, as the CDC cleanup job does."""
    retention = con.execute("select retention_days from clock.state").fetchone()[0]
    cutoff = dt.datetime.combine(today - dt.timedelta(days=retention), dt.time(23, 59))
    purged = [r[0] for r in con.execute(
        "select start_lsn from cdc.lsn_time_mapping where tran_begin_time < ?", [cutoff]
    ).fetchall()]
    if not purged:
        return low_water
    for table in X3_KEYS:
        con.execute(f"delete from cdc.{_q('dbo_' + table + '_CT')} "
                    "where \"__$start_lsn\" <= ?", [max(purged)])
    con.execute("delete from cdc.lsn_time_mapping where start_lsn <= ?", [max(purged)])
    return max(low_water, int(max(purged), 16))


def status() -> dict:
    with connect(read_only=True) as con:
        clk = _clock(con)
        pending = 0
        for table in X3_KEYS:
            pending += con.execute(
                f"select count(*) from cdc.{_q('dbo_' + table + '_CT')}").fetchone()[0]
    return {**clk, "change_rows_retained": pending}


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m sources.clock", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    pi = sub.add_parser("init", help="rebuild the sources as of a day (default INITIAL_DATE)")
    pi.add_argument("--as-of", type=dt.date.fromisoformat)
    pa_ = sub.add_parser("advance", help="move the sources forward")
    pa_.add_argument("--days", type=int, default=1)
    sub.add_parser("status")
    args = p.parse_args()
    if args.cmd == "init":
        init(args.as_of)
        print(f"Sources initialised as of {status()['today']} in {settings.mock_db}")
    elif args.cmd == "advance":
        for day, n in advance(args.days):
            print(f"{day}: {n:,} change rows captured")
    else:
        for k, v in status().items():
            print(f"{k:<24} {v}")


if __name__ == "__main__":
    main()
