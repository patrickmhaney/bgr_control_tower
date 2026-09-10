#!/usr/bin/env python
"""Query anything in the project from one prompt.

    python scripts/q.py                      interactive
    python scripts/q.py "select 1"           one-shot
    python scripts/q.py --ls                 what is queryable
    python scripts/q.py --ls core            filtered
    python scripts/q.py -d fct_shipment      columns and types
    python scripts/q.py --csv "select ..."   pipe-friendly output

Three databases are attached read-only under stable names, so a query can
join across the whole pipeline in one statement:

    mock_sources   the source systems, as if you had a connection to each
    raw            what the ingestion pipeline landed
    warehouse      what dbt built  (the default catalog - no prefix needed)

Read-only throughout. dbt holds a write lock while it runs, so finish a
`dbt build` before querying.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys

import duckdb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ATTACH = [
    ("warehouse", "warehouse.duckdb", "what dbt built"),
    ("raw", "raw.duckdb", "what ingestion landed"),
    ("mock_sources", "mock_sources.duckdb", "the source systems"),
]

LAYERS = {
    "main_staging": "staging      1:1 with source tables, cleaning only",
    "main_intermediate": "intermediate crosswalks and entity resolution",
    "main_core": "core         the dimensional model",
    "main_metrics": "metrics      numerator/denominator per dimension",
    "main_process": "process      the nine dashboard views",
    "main_seed": "seed         process map, crosswalk, metric registry",
    "snapshot": "snapshot     Type 2 history, accumulating. Nothing reads it yet",
}

EXAMPLES = """
  -- the model
  select * from fct_shipment limit 5;
  select site_code, count(*), round(avg(shipment_cost_usd),2) from fct_shipment group by 1;

  -- a metric, rolled up
  select round(100.0*sum(numerator)/sum(denominator),1) as otd from mtr_on_time_delivery_rate;

  -- a dashboard
  select slot, metric_label, metric_status from mart_i2d order by slot;

  -- across the whole pipeline in one query
  select (select count(*) from mock_sources.pangea.shipment) as at_source,
         (select count(*) from raw.pangea.shipment)          as landed,
         (select count(*) from main_core.fct_shipment)       as modelled;

  -- straight off the landing archive, no database involved
  select count(*) from read_parquet('landing/pangea/shipment/**/*.parquet');
"""


def connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    missing = []
    for alias, filename, _ in ATTACH:
        path = os.path.join(ROOT, filename)
        if not os.path.exists(path):
            missing.append((alias, filename))
            continue
        try:
            con.execute(f"attach '{path}' as {alias} (read_only)")
        except duckdb.Error as exc:
            raise SystemExit(
                f"cannot open {filename}: {exc}\n"
                f"If dbt or run_ingestion.py is running, wait for it to finish - "
                f"DuckDB allows one writer at a time."
            )
    if missing:
        for alias, filename in missing:
            hint = ("run `python run_ingestion.py`" if alias == "raw"
                    else "run `dbt build`")
            print(f"note: {filename} not found - {hint}", file=sys.stderr)
    con.execute("use warehouse")
    # Resolve unqualified names across every dbt layer, so exploration reads
    # `fct_shipment` rather than `warehouse.main_core.fct_shipment`. Built from
    # the schemas that actually exist, so this still works before a dbt build.
    preferred = ["main_core", "main_metrics", "main_process", "main_intermediate",
                 "main_staging", "main_seed", "snapshot", "main_semantic", "main"]
    present = {r[0] for r in con.execute(
        "select schema_name from duckdb_schemas() where database_name = 'warehouse'"
    ).fetchall()}
    path = ",".join(f"warehouse.{s}" for s in preferred if s in present)
    if path:
        con.execute(f"set search_path = '{path}'")
    return con


def render(rel, limit: int) -> None:
    columns = rel.columns
    rows = rel.fetchall()
    shown = rows[:limit]
    cells = [[fmt(v) for v in row] for row in shown]
    widths = [
        min(60, max(len(c), *(len(r[i]) for r in cells)) if cells else len(c))
        for i, c in enumerate(columns)
    ]
    print("  " + "  ".join(c[:widths[i]].ljust(widths[i]) for i, c in enumerate(columns)))
    print("  " + "  ".join("-" * w for w in widths))
    for row in cells:
        print("  " + "  ".join(v[:widths[i]].ljust(widths[i]) for i, v in enumerate(row)))
    suffix = f"  (showing {len(shown)})" if len(rows) > len(shown) else ""
    print(f"\n  {len(rows)} row{'s' if len(rows) != 1 else ''}{suffix}")


def fmt(value) -> str:
    if value is None:
        return "·"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:,.4f}".rstrip("0").rstrip(".")
    return str(value)


def list_objects(con, pattern: str | None) -> None:
    print("\nattached databases")
    for alias, filename, note in ATTACH:
        exists = os.path.exists(os.path.join(ROOT, filename))
        print(f"  {alias:14} {'ok    ' if exists else 'absent'}  {note}")

    print("\nwarehouse - dbt output (queryable without a prefix)")
    rows = con.execute("""
        select schema_name, table_name, 'table' as kind from duckdb_tables()
          where database_name = 'warehouse'
        union all
        select schema_name, view_name, 'view' from duckdb_views()
          where database_name = 'warehouse' and not internal
        order by 1, 2
    """).fetchall()
    current = None
    for schema, name, kind in rows:
        if pattern and pattern.lower() not in f"{schema} {name}".lower():
            continue
        if schema != current:
            current = schema
            print(f"\n  {LAYERS.get(schema, schema)}")
        print(f"    {name:44} {kind}")

    if not pattern:
        print("\nraw / mock_sources - one schema per source system")
        for alias in ("raw", "mock_sources"):
            if not os.path.exists(os.path.join(ROOT, f"{alias.replace('mock_sources','mock_sources')}.duckdb")):
                continue
            counts = con.execute(
                "select schema_name, count(*) from duckdb_tables() "
                "where database_name = ? group by 1 order by 1", [alias]).fetchall()
            inline = "  ".join(f"{s} ({n})" for s, n in counts)
            print(f"  {alias:14} {inline}")
        print(EXAMPLES)


def describe(con, name: str) -> None:
    rows = con.execute("""
        select database_name, schema_name, table_name, column_name, data_type
        from duckdb_columns()
        where lower(table_name) = lower(?)
        order by database_name, schema_name, column_index
    """, [name]).fetchall()
    if not rows:
        print(f"no object named {name!r}. Try --ls {name}", file=sys.stderr)
        return
    current = None
    for db, schema, table, column, dtype in rows:
        key = (db, schema, table)
        if key != current:
            current = key
            qualified = f"{db}.{schema}.{table}"
            try:
                n = con.execute(f'select count(*) from "{db}"."{schema}"."{table}"').fetchone()[0]
                print(f"\n{qualified}   {n:,} rows")
            except duckdb.Error:
                print(f"\n{qualified}")
            print("-" * max(40, len(qualified) + 14))
        print(f"  {column:44} {dtype}")


def repl(con, limit: int) -> None:
    try:
        import readline  # noqa: F401  - gives history and line editing
    except ImportError:
        pass
    print(__doc__.split("Three databases")[0].strip().split("\n")[0])
    print("attached: warehouse (default), raw, mock_sources - all read-only")
    print("\\l list objects   \\d <table> describe   \\q quit   end statements with ;\n")
    buffer: list[str] = []
    while True:
        try:
            line = input("… " if buffer else "q> ")
        except (EOFError, KeyboardInterrupt):
            print()
            return
        stripped = line.strip()
        if not buffer and stripped in ("\\q", "quit", "exit"):
            return
        if not buffer and stripped == "\\l":
            list_objects(con, None)
            continue
        if not buffer and stripped.startswith("\\d "):
            describe(con, stripped[3:].strip())
            continue
        if not stripped:
            continue
        buffer.append(line)
        if not stripped.endswith(";"):
            continue
        sql = "\n".join(buffer).rstrip().rstrip(";")
        buffer = []
        try:
            render(con.sql(sql), limit)
        except duckdb.Error as exc:
            print(f"  error: {exc}", file=sys.stderr)
        print()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sql", nargs="?", help="SQL to run; omit for an interactive prompt")
    parser.add_argument("--ls", nargs="?", const="", metavar="FILTER",
                        help="list queryable objects, optionally filtered")
    parser.add_argument("-d", "--describe", metavar="TABLE", help="columns and row count")
    parser.add_argument("-n", "--limit", type=int, default=40, help="rows to print (default 40)")
    parser.add_argument("--csv", action="store_true", help="emit CSV instead of a table")
    args = parser.parse_args()

    con = connect()
    try:
        if args.ls is not None:
            list_objects(con, args.ls or None)
            return 0
        if args.describe:
            describe(con, args.describe)
            return 0
        if not args.sql:
            repl(con, args.limit)
            return 0

        rel = con.sql(args.sql.rstrip().rstrip(";"))
        if args.csv:
            writer = csv.writer(sys.stdout)
            writer.writerow(rel.columns)
            writer.writerows(rel.fetchall())
        else:
            render(rel, args.limit)
        return 0
    except duckdb.Error as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
