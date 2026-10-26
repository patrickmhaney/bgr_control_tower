"""Materialise the MetricFlow saved queries as cubes, and stack them for Power BI.

    python -m serving.materialize

Each saved query in the pack's models/semantic/saved_queries.yml is compiled
through the semantic service into SQL and written to the warehouse's `marts`
schema as a table. Beside every ratio it stores the numerator and denominator,
so a reader can roll the rows up correctly (semantic/rollup.py).

Then every mart is stacked into one table, marts.dashboard_cube, with a
`_cube` column naming the saved query it came from. Columns are shared: a
dimension or a metric has the same column in every cube that carries it, and
is null in the others. That one table is what Power BI imports. Every mart,
the stack included, is also written as Parquet under <exports_root>/marts/.
"""
from __future__ import annotations

import duckdb

from core import project, storage
from core.settings import settings
from semantic.rollup import cube_columns, group_by_names
from semantic.rollup import load as load_rollups
from serving.semantic_service import SemanticService

CUBE = "dashboard_cube"


def saved_queries() -> list[dict]:
    return load_rollups(project.current().semantic_manifest)[0].get("saved_queries", [])


def _export(con, name: str) -> None:
    table = con.execute(f'select * from marts."{name}"').fetch_arrow_table()
    storage.write_parquet(storage.join(settings.exports_root, "marts", f"{name}.parquet"), table)


def materialize() -> dict[str, int]:
    svc = SemanticService()
    sm, rollups = load_rollups(project.current().semantic_manifest)
    cumulative = {m["name"] for m in sm["metrics"] if m["type"] == "cumulative"}
    as_of = svc.as_of_date().isoformat()
    counts = {}
    con = duckdb.connect(settings.warehouse_path)
    try:
        con.execute("create schema if not exists marts")
        names, dims, columns = [], [], []
        for sq in sm.get("saved_queries", []):
            name = sq["name"]
            metrics = cube_columns(sq, rollups)
            where = [w["where_sql_template"]
                     for w in (sq["query_params"].get("where") or {}).get("where_filters", [])]
            # A rolling window must not run past the data, as in the semantic service.
            end = as_of if cumulative & set(metrics) else None
            sql = svc.compile(metrics, group_by_names(sq), where=where, end=end)
            con.execute(f'create or replace table marts."{name}" as {sql}')
            # A row with no value for any metric carries no information.
            con.execute(f'delete from marts."{name}" where '
                        + " and ".join(f'"{m}" is null' for m in metrics))
            # Periods are dates, not timestamps, so no consumer shifts them by a time zone.
            for (col,) in con.execute(
                    "select column_name from duckdb_columns() where schema_name = 'marts' "
                    "and table_name = ? and column_name like 'metric_time__%'", [name]).fetchall():
                con.execute(f'alter table marts."{name}" alter column "{col}" type date')
            counts[name] = con.execute(f'select count(*) from marts."{name}"').fetchone()[0]
            _export(con, name)
            names.append(name)
            dims += [d for d in group_by_names(sq) if d not in dims]
            columns += [m for m in metrics if m not in columns]
            print(f"mart {name:<28} {counts[name]:>6,} rows")

        stacked = " union all by name ".join(f"select '{n}' as _cube, * from marts.\"{n}\""
                                             for n in names)
        ordered = ", ".join(f'"{c}"' for c in ["_cube", *dims, *columns])
        con.execute(f'create or replace table marts."{CUBE}" as select {ordered} from ({stacked})')
        counts[CUBE] = con.execute(f'select count(*) from marts."{CUBE}"').fetchone()[0]
        _export(con, CUBE)
        width = len(con.execute(f'select * from marts."{CUBE}" limit 0').description)
        print(f"cube {CUBE:<28} {counts[CUBE]:>6,} rows x {width} columns")
    finally:
        con.close()
    return counts


if __name__ == "__main__":
    materialize()
