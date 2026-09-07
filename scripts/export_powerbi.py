"""Export the Power BI slice: Parquet data plus a generated TMDL model.

    python scripts/export_powerbi.py
    python scripts/export_powerbi.py --process I2D

Parquet rather than a live DuckDB connection because fighting
DuckDB-to-Power-BI connectivity is not what a POC is for. Import mode is also
the right end state for a star schema this size - the whole model is under
40,000 rows in the fact tables.

The TMDL model is generated from three inputs and no hand-written measure:

    warehouse.duckdb schema  ->  tables and columns
    semantic/models.yml      ->  which columns are keys
    semantic/metrics/        ->  measures, via compile_metrics.dax_measure

That last one is the point. The DAX in the Power BI model and the SQL in the
warehouse come from the same metric definition, so a change to a metric cannot
land in one and not the other.

Honest limitation: the TMDL is structurally generated and schema-checked here,
but it has not been opened in Power BI Desktop - that is not possible in this
environment. Treat it as a validated starting point for the model author, not
as a signed-off artefact. What it does guarantee is that no measure was typed
by hand.
"""
import argparse
import csv
import json
import os
import shutil
import sys

import duckdb
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from compile_metrics import (  # noqa: E402
    DAX_FORMAT, dax_measure, is_reaggregatable, load_registry, validate,
)

WAREHOUSE = os.path.join(ROOT, "warehouse.duckdb")
EXPORT_ROOT = os.path.join(ROOT, "exports")
PARQUET_DIR = os.path.join(EXPORT_ROOT, "parquet")
TMDL_DIR = os.path.join(EXPORT_ROOT, "powerbi", "model", "definition")

# The conformed core. Exported whole rather than per-dashboard: one shared
# semantic model over the core is the recommendation, and slicing the export
# per dashboard would quietly re-create the nine-model topology it argues
# against.
CORE_TABLES = [
    ("main_core", "dim_date"),
    ("main_core", "dim_customer"),
    ("main_core", "dim_site"),
    ("main_core", "dim_item"),
    ("main_core", "dim_carrier"),
    ("main_core", "fct_shipment"),
    ("main_core", "fct_shipment_event"),
    ("main_core", "fct_sales_order_line"),
    ("main_core", "fct_invoice_line"),
    ("main_core", "fct_supplier_invoice_line"),
    ("main_core", "fct_inventory_count_line"),
    ("main_seed", "metric_registry"),
    ("main_seed", "process_metric_map"),
    ("main_seed", "process"),
]

# Star-schema relationships. Declared here rather than inferred because a
# generated relationship that is wrong is worse than one an author has to type:
# these are the joins the dbt relationship tests already prove hold.
RELATIONSHIPS = [
    ("fct_shipment", "ship_date_key", "dim_date", "date_key"),
    ("fct_shipment", "customer_key", "dim_customer", "customer_key"),
    ("fct_shipment", "site_code", "dim_site", "site_code"),
    ("fct_shipment", "carrier_scac", "dim_carrier", "carrier_scac"),
    ("fct_shipment_event", "event_date_key", "dim_date", "date_key"),
    ("fct_shipment_event", "customer_key", "dim_customer", "customer_key"),
    ("fct_shipment_event", "site_code", "dim_site", "site_code"),
    ("fct_shipment_event", "carrier_scac", "dim_carrier", "carrier_scac"),
    ("fct_sales_order_line", "order_date_key", "dim_date", "date_key"),
    ("fct_sales_order_line", "customer_key", "dim_customer", "customer_key"),
    ("fct_sales_order_line", "site_code", "dim_site", "site_code"),
    ("fct_sales_order_line", "item_code", "dim_item", "item_code"),
    ("fct_invoice_line", "invoice_date_key", "dim_date", "date_key"),
    ("fct_invoice_line", "customer_key", "dim_customer", "customer_key"),
    ("fct_invoice_line", "site_code", "dim_site", "site_code"),
    ("fct_invoice_line", "item_code", "dim_item", "item_code"),
    # Neither purchasing nor counting has a customer or a carrier, so these
    # facts join three of the five conformed dimensions and not the other two.
    # That is what a conformed bus matrix looks like when it is honest.
    ("fct_supplier_invoice_line", "invoice_date_key", "dim_date", "date_key"),
    ("fct_supplier_invoice_line", "site_code", "dim_site", "site_code"),
    ("fct_supplier_invoice_line", "item_code", "dim_item", "item_code"),
    ("fct_inventory_count_line", "count_date_key", "dim_date", "date_key"),
    ("fct_inventory_count_line", "site_code", "dim_site", "site_code"),
    ("fct_inventory_count_line", "item_code", "dim_item", "item_code"),
]

DUCKDB_TO_TMDL = {
    "BOOLEAN": ("boolean", "boolean"),
    "TINYINT": ("int64", "int64"),
    "SMALLINT": ("int64", "int64"),
    "INTEGER": ("int64", "int64"),
    "BIGINT": ("int64", "int64"),
    "HUGEINT": ("int64", "int64"),
    "FLOAT": ("double", "double"),
    "DOUBLE": ("double", "double"),
    "DATE": ("dateTime", "dateTime"),
    "TIMESTAMP": ("dateTime", "dateTime"),
    "VARCHAR": ("string", "string"),
}


def tmdl_type(duckdb_type):
    base = duckdb_type.split("(")[0].upper()
    if base.startswith("DECIMAL"):
        return ("decimal", "decimal")
    return DUCKDB_TO_TMDL.get(base, ("string", "string"))


def export_parquet(con):
    os.makedirs(PARQUET_DIR, exist_ok=True)
    manifest = []
    for schema, table in CORE_TABLES:
        path = os.path.join(PARQUET_DIR, f"{table}.parquet")
        con.execute(
            f"copy (select * from {schema}.{table}) to '{path}' "
            f"(format parquet, compression zstd)"
        )
        rows = con.sql(f"select count(*) from {schema}.{table}").fetchone()[0]
        manifest.append({
            "table": table,
            "source": f"{schema}.{table}",
            "rows": rows,
            "file": os.path.relpath(path, ROOT),
            "bytes": os.path.getsize(path),
        })
        print(f"  {table:24} {rows:>8,} rows  {os.path.getsize(path)/1024:>8.1f} KiB")
    return manifest


def export_metric_parquet(con, metrics):
    written = []
    for metric in metrics:
        if metric["status"] == "blocked":
            continue
        table = f"mtr_{metric['name']}"
        path = os.path.join(PARQUET_DIR, f"{table}.parquet")
        con.execute(
            f"copy (select * from main_metrics.{table}) to '{path}' "
            f"(format parquet, compression zstd)"
        )
        written.append(table)
    print(f"  {len(written)} pre-aggregated metric tables "
          f"(reference only - the measures compute from the facts)")
    return written


def export_process_parquet(con, processes):
    written = []
    for code in processes:
        table = f"mart_{code.lower()}"
        path = os.path.join(PARQUET_DIR, f"{table}.parquet")
        con.execute(
            f"copy (select * from main_process.{table}) to '{path}' "
            f"(format parquet, compression zstd)"
        )
        written.append(table)
    return written


def column_lines(con, schema, table, key_columns):
    lines = []
    columns = con.sql(f"""
        select column_name, data_type
        from duckdb_columns()
        where schema_name = '{schema}' and table_name = '{table}'
        order by column_index
    """).fetchall()
    for name, dtype in columns:
        data_type, summarise = tmdl_type(dtype)
        lines.append(f"\tcolumn {name}")
        lines.append(f"\t\tdataType: {data_type}")
        if data_type in ("int64", "double", "decimal") and name not in key_columns:
            lines.append("\t\tsummarizeBy: sum")
        else:
            lines.append("\t\tsummarizeBy: none")
        if name in key_columns:
            lines.append("\t\tisKey")
        lines.append(f"\t\tsourceColumn: {name}")
        lines.append("")
    return lines


def partition_lines(table):
    """M query reading the Parquet file. Relative to a parameterised folder so
    the model author sets the path once instead of editing every table."""
    return [
        f"\tpartition {table} = m",
        "\t\tmode: import",
        "\t\tsource =",
        "\t\t\t\tlet",
        f'\t\t\t\t    Source = Parquet.Document(File.Contents(ExportFolder & "{table}.parquet"))',
        "\t\t\t\tin",
        "\t\t\t\t    Source",
        "",
    ]


def measure_lines(table, metrics, models):
    lines = []
    for metric in metrics:
        if metric["status"] == "blocked" or metric["base_model"] != table:
            continue
        fmt = DAX_FORMAT.get(metric.get("format", ""), '"#,0.00"')
        description = " ".join(metric["description"].split())
        folder = {"active": "Metrics", "provisional": "Metrics\\Provisional"}[metric["status"]]
        lines += [
            f"\tmeasure '{metric['label']}' = {dax_measure(metric, models)}",
            f"\t\tformatString: {fmt}",
            f"\t\tdisplayFolder: {folder}",
            f"\t\t/// {description}",
            f"\t\tannotation MetricName = {metric['name']}",
            f"\t\tannotation MetricStatus = {metric['status']}",
            f"\t\tannotation MetricOwner = {metric.get('owner')}",
            f"\t\tannotation MetricReaggregatable = {str(is_reaggregatable(metric)).lower()}",
            f"\t\tannotation DefinitionFile = {metric['_file']}",
            "",
        ]
    return lines


def key_columns_for(table):
    keys = {
        "dim_date": {"date_key"},
        "dim_customer": {"customer_key"},
        "dim_site": {"site_code"},
        "dim_item": {"item_code"},
        "dim_carrier": {"carrier_scac"},
        "metric_registry": {"metric_name"},
        "process": {"process_code"},
    }
    return keys.get(table, set())


def generate_tmdl(con, dimensions, models, metrics):
    if os.path.isdir(TMDL_DIR):
        shutil.rmtree(TMDL_DIR)
    os.makedirs(os.path.join(TMDL_DIR, "tables"), exist_ok=True)

    table_names = []
    for schema, table in CORE_TABLES:
        lines = [
            "/// Generated by scripts/export_powerbi.py. Measures come from",
            "/// semantic/metrics/ via scripts/compile_metrics.py - never hand-written.",
            f"table {table}",
            "",
        ]
        lines += column_lines(con, schema, table, key_columns_for(table))
        lines += measure_lines(table, metrics, models)
        lines += partition_lines(table)
        with open(os.path.join(TMDL_DIR, "tables", f"{table}.tmdl"), "w") as fh:
            fh.write("\n".join(lines))
        table_names.append(table)

    model_lines = [
        "/// Generated by scripts/export_powerbi.py.",
        "///",
        "/// One shared semantic model over the conformed core, with nine reports",
        "/// against it - not nine models. See docs/powerbi_model.md for the",
        "/// reasoning and the rollout implications.",
        "model Model",
        "\tculture: en-US",
        "\tdefaultPowerBIDataSourceVersion: powerBI_V3",
        "\tdiscourageImplicitMeasures",
        "",
    ]
    for table in table_names:
        model_lines.append(f"ref table {table}")
    model_lines.append("")

    for from_table, from_column, to_table, to_column in RELATIONSHIPS:
        name = f"{from_table}_{from_column}_to_{to_table}"
        model_lines += [
            f"relationship {name}",
            f"\tfromColumn: {from_table}.{from_column}",
            f"\ttoColumn: {to_table}.{to_column}",
            "\tcrossFilteringBehavior: oneDirection",
            "",
        ]

    with open(os.path.join(TMDL_DIR, "model.tmdl"), "w") as fh:
        fh.write("\n".join(model_lines))

    with open(os.path.join(TMDL_DIR, "database.tmdl"), "w") as fh:
        fh.write("database ControlTower\n\tcompatibilityLevel: 1567\n")

    with open(os.path.join(TMDL_DIR, "expressions.tmdl"), "w") as fh:
        # A required, empty parameter rather than a guessed path: Power BI
        # prompts for it on first open, which is better than silently pointing
        # at a directory that exists on whoever generated the model.
        fh.write(
            "/// Absolute path to the folder holding the exported Parquet files,\n"
            "/// with a trailing separator. Power BI prompts for this on first open.\n"
            "/// Example: C:\\\\bgr_control_tower\\\\exports\\\\parquet\\\\  or  /srv/bgr_control_tower/exports/parquet/\n"
            "expression ExportFolder = \"\" "
            "meta [IsParameterQuery=true, Type=\"Text\", IsParameterQueryRequired=true]\n"
            "\tlineageTag: export-folder-parameter\n"
        )

    return table_names


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--process", default=None,
                        help="report which process the slice targets (documentation only)")
    args = parser.parse_args()

    dimensions, models, metrics = load_registry()
    validate(dimensions, models, metrics)

    con = duckdb.connect(WAREHOUSE, read_only=True)
    try:
        processes = [r[0] for r in con.sql(
            "select process_code from main_seed.process order by display_order").fetchall()]

        print("Parquet export")
        manifest = export_parquet(con)
        metric_tables = export_metric_parquet(con, metrics)
        process_tables = export_process_parquet(con, processes)

        print("\nTMDL model")
        tables = generate_tmdl(con, dimensions, models, metrics)
        measures = sum(
            1 for m in metrics
            if m["status"] != "blocked" and m["base_model"] in tables
        )
        print(f"  {len(tables)} tables, {len(RELATIONSHIPS)} relationships, "
              f"{measures} generated measures, 0 hand-written")

        summary = {
            "target_process": args.process,
            "parquet": manifest,
            "metric_tables": metric_tables,
            "process_tables": process_tables,
            "tmdl_tables": tables,
            "relationships": [
                {"from": f"{a}.{b}", "to": f"{c}.{d}"} for a, b, c, d in RELATIONSHIPS
            ],
            "generated_measures": measures,
            "hand_written_measures": 0,
        }
        with open(os.path.join(EXPORT_ROOT, "export_manifest.json"), "w") as fh:
            json.dump(summary, fh, indent=2)
        print(f"\n  manifest -> exports/export_manifest.json")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
