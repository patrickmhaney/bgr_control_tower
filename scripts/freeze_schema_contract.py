"""Freeze the expected source schema into ingestion/schema_contract.json.

    python scripts/freeze_schema_contract.py

Why a contract is not optional
------------------------------
Every ingestion tool infers schema from the rows it happens to see, and dlt is
no exception. On the first run of this pipeline, `paycom.employee` arrived with
`rehire_date` and `manager_ee_id` null on all 150 rows, so dlt could not infer
a type and dropped both columns. Staging references them. The pipeline "worked"
and the warehouse was wrong.

That failure mode is not specific to dlt - Fivetran, Airbyte and every
hand-rolled extractor share it, because a column that is null everywhere is
indistinguishable from a column that is not there. The fix is the same
everywhere: declare the expected schema, hand it to the loader as type hints,
and compare what arrives against it on every run.

The contract also gives you drift detection for free, which is the thing that
actually protects a production pipeline. A source that gains a column is a
feature request; a source that loses one is an incident, and today neither
announces itself.

In production this file is generated once from a reviewed extract and then
committed and changed deliberately. Regenerating it silently to make a failing
run pass is the one thing you must not do.
"""
from __future__ import annotations

import json
import os
import sys

import duckdb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ingestion.config import SOURCES  # noqa: E402

CONTRACT = os.path.join(ROOT, "ingestion", "schema_contract.json")
MOCK_DB = os.path.join(ROOT, "mock_sources.duckdb")

# DuckDB catalogue types -> dlt data types.
TYPE_MAP = {
    "VARCHAR": "text",
    "BOOLEAN": "bool",
    "TINYINT": "bigint",
    "SMALLINT": "bigint",
    "INTEGER": "bigint",
    "BIGINT": "bigint",
    "HUGEINT": "bigint",
    "FLOAT": "double",
    "DOUBLE": "double",
    "DATE": "date",
    "TIMESTAMP": "timestamp",
    "TIME": "time",
    "BLOB": "binary",
}


def dlt_type(duckdb_type: str) -> dict:
    base = duckdb_type.split("(")[0].upper()
    if base == "DECIMAL":
        inner = duckdb_type[duckdb_type.index("(") + 1: -1]
        precision, scale = (int(x) for x in inner.split(","))
        return {"data_type": "decimal", "precision": precision, "scale": scale}
    return {"data_type": TYPE_MAP.get(base, "text")}


def main() -> int:
    con = duckdb.connect(MOCK_DB, read_only=True)
    contract: dict[str, dict[str, dict]] = {}
    for source in SOURCES.values():
        contract[source.name] = {}
        for spec in source.tables:
            rows = con.execute(
                "select column_name, data_type from duckdb_columns() "
                "where schema_name = ? and table_name = ? order by column_index",
                [source.name, spec.name],
            ).fetchall()
            if not rows:
                print(f"  WARNING {source.name}.{spec.name} not found in the source",
                      file=sys.stderr)
                continue
            contract[source.name][spec.name] = {
                name: {**dlt_type(dtype), "nullable": True} for name, dtype in rows
            }
    con.close()

    with open(CONTRACT, "w") as fh:
        json.dump(contract, fh, indent=1, sort_keys=False)
        fh.write("\n")

    tables = sum(len(t) for t in contract.values())
    columns = sum(len(c) for t in contract.values() for c in t.values())
    print(f"froze {tables} tables / {columns} columns -> "
          f"{os.path.relpath(CONTRACT, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
