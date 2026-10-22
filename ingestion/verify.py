"""Contract C2, checked: bronze's current state equals what each source shows.

    python -m ingestion.verify

Compares every source table, every column, every row, with the bronze model
that rebuilds it from the changelog (`bronze_current`), after
`python -m ctl build --stage raw`. The convergence test runs it after walking
the clock through gaps and deletes; the Studio runs it after every extract.
"""
from __future__ import annotations

import sys

import duckdb

from core.settings import settings

SOURCES = ("sage_x3", "hubspot", "netstock", "azure_cost")


def compare(warehouse_path: str | None = None, mock_db: str | None = None) -> list[dict]:
    """One entry per source table: rows the source has that bronze lacks, and the reverse."""
    con = duckdb.connect(warehouse_path or settings.warehouse_path, read_only=True)
    try:
        con.execute(f"attach '{mock_db or settings.mock_db}' as src (read_only)")
        out = []
        for schema in SOURCES:
            for (table,) in con.execute("select table_name from duckdb_tables() where database_name "
                                        "= 'src' and schema_name = ? order by 1", [schema]).fetchall():
                cols = ", ".join(f'"{c}"' for (c,) in con.execute(
                    "select column_name from duckdb_columns() where database_name = 'src' "
                    "and schema_name = ? and table_name = ?", [schema, table]).fetchall())
                source = f'src.{schema}."{table}"'
                bronze = f'bronze."bronze_{schema}__{table.lower()}"'
                rows, missing, extra = con.execute(
                    f"select (select count(*) from {source}), "
                    f"(select count(*) from (select {cols} from {source} except select {cols} from {bronze})), "
                    f"(select count(*) from (select {cols} from {bronze} except select {cols} from {source}))"
                ).fetchone()
                out.append({"source": schema, "table": table, "rows": rows,
                            "missing": missing, "extra": extra})
        return out
    finally:
        con.close()


def differences(warehouse_path: str | None = None, mock_db: str | None = None) -> list[str]:
    return [f"{t['source']}.{t['table']}: missing {t['missing']}, extra {t['extra']}"
            for t in compare(warehouse_path, mock_db) if t["missing"] or t["extra"]]


if __name__ == "__main__":
    tables = compare()
    bad = [t for t in tables if t["missing"] or t["extra"]]
    for t in bad:
        print(f"FAIL {t['source']}.{t['table']}: missing {t['missing']}, extra {t['extra']}")
    print(f"{len(tables) - len(bad)} of {len(tables)} source tables match bronze exactly.")
    sys.exit(1 if bad else 0)
