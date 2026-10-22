"""Reverse load: copy the marts into the serving database for apps (contract C7).

    python -m serving.reverse_load

Apps read Postgres, not the warehouse file: Postgres handles many concurrent
readers and app write-back, a DuckDB file does not. dlt does the copy, so the
destination is configuration - `postgres` in Azure (Azure Database for
PostgreSQL, or any plain Postgres such as Snowflake Postgres), `duckdb`
locally. Each mart's columns are frozen after the first load, so a change in a
saved query is a reviewed change to C7, not a surprise for an app.
"""
from __future__ import annotations

import os

import dlt
import duckdb

from core.settings import settings

DATASET = "marts"


def _marts() -> list[str]:
    con = duckdb.connect(settings.warehouse_path, read_only=True)
    try:
        return [r[0] for r in con.execute(
            "select table_name from duckdb_tables() where schema_name = 'marts' order by 1"
        ).fetchall()]
    finally:
        con.close()


def _resource(name: str):
    def rows():
        con = duckdb.connect(settings.warehouse_path, read_only=True)
        try:
            yield con.execute(f'select * from marts."{name}"').fetch_arrow_table()
        finally:
            con.close()
    return dlt.resource(rows, name=name, write_disposition="replace")


def destination():
    if settings.serving_destination == "postgres":
        password = os.environ.get("CT_SERVING_PASSWORD", "")
        url = settings.serving_url
        if password and "@" in url and ":" not in url.split("//", 1)[1].split("@", 1)[0]:
            user, rest = url.split("//", 1)[1].split("@", 1)
            url = f"postgresql://{user}:{password}@{rest}"
        return dlt.destinations.postgres(credentials=url)
    return dlt.destinations.duckdb(credentials=settings.serving_url)


def load_serving() -> dict[str, int]:
    marts = _marts()
    if not marts:
        raise SystemExit("No marts yet. Run `python -m ctl materialize` first.")
    pipeline = dlt.pipeline(pipeline_name="serving", destination=destination(),
                            dataset_name=DATASET,
                            pipelines_dir=os.path.join(settings.data_dir, "dlt"), progress=None)
    pipeline.run([_resource(m) for m in marts])
    counts = dict(pipeline.last_trace.last_normalize_info.row_counts)
    counts = {k: v for k, v in counts.items() if not k.startswith("_dlt")}
    print(f"serving: {len(counts)} marts -> {settings.serving_destination}")
    return counts


if __name__ == "__main__":
    load_serving()
