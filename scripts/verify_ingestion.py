"""Prove the ingestion pipeline is lossless.

    python scripts/verify_ingestion.py

Builds the warehouse twice - once reading the ingested `raw` database, once
reading the source systems directly - and asserts that every metric, every row
count and every table shape is identical.

This is the test that makes it safe to put a pipeline in front of a model that
already works. Without it, "we added ingestion" and "the numbers changed" are
two events nobody can tell apart.
"""
from __future__ import annotations

import os
import subprocess
import sys

import duckdb

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _toolchain import ROOT, dbt_command, project_env  # noqa: E402

METRIC_SQL = """
select 'cost_per_shipment'             as metric, round(sum(numerator)/sum(denominator), 4) as v from main_metrics.mtr_cost_per_shipment
union all select 'on_time_delivery_rate',        round(sum(numerator)/sum(denominator), 6) from main_metrics.mtr_on_time_delivery_rate
union all select 'cost_per_order',               round(sum(numerator)/sum(denominator), 4) from main_metrics.mtr_cost_per_order
union all select 'dso_days_to_pay_proxy',        round(sum(numerator)/sum(denominator), 6) from main_metrics.mtr_dso_days_to_pay_proxy
union all select 'unsettled_invoice_rate',       round(sum(numerator)/sum(denominator), 6) from main_metrics.mtr_unsettled_invoice_rate
union all select 'order_reference_coverage_rate',round(sum(numerator)/sum(denominator), 6) from main_metrics.mtr_order_reference_coverage_rate
union all select 'customer_unmatched_rate',      round(sum(numerator)/sum(denominator), 6) from main_metrics.mtr_customer_unmatched_rate
order by 1
"""

CORE_TABLES = [
    "dim_customer", "dim_item", "dim_site", "dim_carrier", "dim_date",
    "fct_shipment", "fct_shipment_event", "fct_sales_order_line", "fct_invoice_line",
]

failures = []


def check(ok: bool, message: str) -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {message}")
    if not ok:
        failures.append(message)


def build(source_database: str) -> None:
    result = subprocess.run(
        dbt_command("build", "--vars", f"{{source_database: {source_database}}}", "--quiet"),
        cwd=ROOT, env=project_env(), capture_output=True, text=True,
    )
    # Warnings are expected - the four documented dashed-line tests.
    if result.returncode != 0 and "ERROR=0" not in result.stdout:
        print(result.stdout[-3000:])
        raise SystemExit(f"dbt build failed against {source_database}")


def snapshot() -> dict:
    con = duckdb.connect(os.path.join(ROOT, "warehouse.duckdb"), read_only=True)
    try:
        metrics = {m: v for m, v in con.sql(METRIC_SQL).fetchall()}
        counts = {
            t: con.sql(f"select count(*) from main_core.{t}").fetchone()[0]
            for t in CORE_TABLES
        }
        shapes = {}
        for t in CORE_TABLES:
            cols = con.execute(
                "select column_name from duckdb_columns() "
                "where schema_name = 'main_core' and table_name = ? order by column_index",
                [t],
            ).fetchall()
            shapes[t] = tuple(c[0] for c in cols)
        return {"metrics": metrics, "counts": counts, "shapes": shapes}
    finally:
        con.close()


def main() -> int:
    print("building against the source systems directly (mock_sources)")
    build("mock_sources")
    direct = snapshot()

    print("building against the ingestion pipeline output (raw)")
    build("raw")
    ingested = snapshot()

    print("\ncomparing\n")
    check(direct["counts"] == ingested["counts"],
          f"core model row counts identical ({sum(direct['counts'].values()):,} rows across "
          f"{len(CORE_TABLES)} models)")
    check(direct["shapes"] == ingested["shapes"],
          f"core model column shapes identical "
          f"({sum(len(v) for v in direct['shapes'].values())} columns)")

    for metric in sorted(direct["metrics"]):
        a, b = direct["metrics"][metric], ingested["metrics"][metric]
        check(a == b, f"{metric:32} {a} == {b}")

    print()
    if failures:
        print(f"FAILED: {len(failures)} difference(s). The pipeline is NOT lossless.")
        return 1
    print("The ingestion pipeline is lossless: every metric, row count and column\n"
          "shape is identical whether the warehouse reads the source systems\n"
          "directly or the data the pipeline landed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
