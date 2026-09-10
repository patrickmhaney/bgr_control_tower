"""Two-stage load: extract to an append-only Parquet archive, then project it
into the raw schema the warehouse reads.

    source systems
         |  dlt resources (ingestion/sources.py)
         v
    landing/<source>/<table>/load_date=YYYY-MM-DD/<load_id>.parquet
         |  immutable, append-only, one file per extract
         |
         |  project_landing_to_raw()  - SQL, no source access
         v
    raw.duckdb  ->  schemas sage_x3, hubspot, paycom, netstock, pangea
         |
         v
    dbt sources

Why two stages rather than loading straight into the warehouse:

* **Replayable.** The raw schema is a pure projection of the archive, so the
  warehouse can be rebuilt from scratch without re-hitting a source system.
  That matters most for the sources you cannot re-read - Paycom exports are
  gone once the next one overwrites them.
* **Auditable.** Every extract is preserved with its load id, so "what did the
  ERP actually return on the 3rd" is answerable.
* **Decoupled.** A failed or partial extract cannot corrupt the raw schema,
  because the projection only runs over complete load packages.

The projection is where write disposition is honoured: replace-style tables
take the newest load package only, merge-style tables union every package and
keep the most recent row per primary key.
"""
from __future__ import annotations

import datetime as dt
import os
import shutil

import dlt
import duckdb

from . import contract
from .config import SOURCES, Strategy
from .sources import BUILDERS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LANDING = os.path.join(ROOT, "landing")
RAW_DB = os.path.join(ROOT, "raw.duckdb")
DLT_HOME = os.path.join(ROOT, "ingestion", "_state")

#: `direct` keeps source column names exactly as they arrive. Fivetran and
#: Airbyte lowercase by default, which would turn ITMREF_0 into itmref_0 and
#: break every staging model. Because staging is GENERATED from a column spec,
#: adapting to a normalising connector is one flag in
#: scripts/generate_staging.py rather than 54 file edits - but the default here
#: is fidelity, so landing records what the source actually sent.
NAMING_CONVENTION = "direct"

LAYOUT = "{table_name}/load_date={YYYY}-{MM}-{DD}/{load_id}.{file_id}.{ext}"


def _configure_env() -> None:
    os.environ["SCHEMA__NAMING"] = NAMING_CONVENTION
    os.environ["DLT_DATA_DIR"] = DLT_HOME
    os.environ["DESTINATION__FILESYSTEM__BUCKET_URL"] = LANDING
    os.environ["DESTINATION__FILESYSTEM__LAYOUT"] = LAYOUT
    # Verified safe for this table set: dlt deletes per-table directories, so
    # the SORDER / SORDERP / SORDERQ prefix overlap does not cause collateral
    # deletion. Re-verify if the layout changes.
    os.environ["DESTINATION__FILESYSTEM__WARN_UNSAFE_LAYOUT_SEPARATORS"] = "false"
    os.environ["RESTORE_FROM_DESTINATION"] = "false"


def extract(source_name: str, full_refresh: bool = False, as_of: dt.date | None = None):
    """Run one source's extract into the landing archive.

    Returns the pipeline and a {table: rows} map for THIS run, which is how the
    incremental behaviour becomes visible: a second run of an unchanged source
    should read far fewer rows than the first.
    """
    _configure_env()
    builder = BUILDERS[source_name]
    kwargs = {}
    if source_name in ("sage_x3", "hubspot", "pangea"):
        kwargs["full_refresh"] = full_refresh
    if source_name == "paycom":
        kwargs["as_of"] = as_of

    pipeline = dlt.pipeline(
        pipeline_name=f"extract_{source_name}",
        destination="filesystem",
        dataset_name=source_name,
        progress=None,
    )
    pipeline.run(builder(**kwargs), loader_file_format="parquet")
    normalize = pipeline.last_trace.last_normalize_info
    counts = dict(normalize.row_counts) if normalize else {}
    counts.pop("_dlt_pipeline_state", None)
    return pipeline, counts


def _landing_glob(source: str, table: str) -> str:
    return os.path.join(LANDING, source, table, "**", "*.parquet").replace("\\", "/")


def project_landing_to_raw(con: duckdb.DuckDBPyConnection, source: str) -> list[tuple[str, int]]:
    """Build raw.<source>.<table> from the landing archive. No source access."""
    con.execute(f'create schema if not exists "{source}"')
    built = []
    for spec in SOURCES[source].tables:
        pattern = _landing_glob(source, spec.name)
        if not _has_files(source, spec.name):
            continue

        scan = (f"read_parquet('{pattern}', hive_partitioning = true, "
                f"union_by_name = true)")

        if spec.write_disposition == "replace":
            # Snapshot semantics: the newest extract IS the truth. Older
            # packages stay in the archive for replay but are not current.
            sql = f"""
                create or replace table "{source}"."{spec.name}" as
                select * exclude (_dlt_load_id, _dlt_id, load_date)
                from {scan}
                where _dlt_load_id = (select max(_dlt_load_id) from {scan})
            """
        else:
            # Merge semantics: union every package, keep the latest row per key.
            keys = ", ".join(f'"{k}"' for k in spec.primary_key)
            sql = f"""
                create or replace table "{source}"."{spec.name}" as
                select * exclude (_dlt_load_id, _dlt_id, load_date)
                from {scan}
                qualify row_number() over (
                    partition by {keys} order by _dlt_load_id desc
                ) = 1
            """
        con.execute(sql)
        n = con.sql(f'select count(*) from "{source}"."{spec.name}"').fetchone()[0]
        built.append((spec.name, n))
    return built


def check_drift(con: duckdb.DuckDBPyConnection, source: str) -> list[contract.Drift]:
    """Compare the raw schema against the pinned contract.

    Runs after projection because that is where a lost column becomes visible.
    A missing column is an incident - something downstream references it - and
    the caller is expected to treat it as one.
    """
    found = []
    for spec in SOURCES[source].tables:
        rows = con.execute(
            "select column_name from duckdb_columns() "
            "where schema_name = ? and table_name = ? order by column_index",
            [source, spec.name],
        ).fetchall()
        if not rows:
            continue
        drift = contract.check(source, spec.name, [r[0] for r in rows])
        if drift:
            found.append(drift)
    return found


def watermarks() -> list[tuple[str, str, str]]:
    """Every stored high-water mark, as (source, table, value).

    Read straight out of dlt's pipeline state. This is what decides how much a
    run reads, so it is the first thing to look at when an incremental extract
    returns more or less than you expected.
    """
    import glob
    import json

    found: dict[tuple[str, str], str] = {}
    for path in sorted(glob.glob(os.path.join(DLT_HOME, "**", "*.json"), recursive=True)):
        try:
            with open(path) as fh:
                state = json.load(fh)
        except (ValueError, OSError):
            continue
        for schema, schema_state in (state.get("sources") or {}).items():
            for table, table_state in (schema_state.get("resources") or {}).items():
                mark = table_state.get("high_water_mark")
                if mark:
                    found[(schema, table)] = mark
    return [(schema, table, mark) for (schema, table), mark in found.items()]


def landed_files(source: str) -> int:
    """Parquet files in the archive for a source. The archive is append-only,
    so this only ever grows - which is how you can see a run happened at all."""
    directory = os.path.join(LANDING, source)
    return sum(
        1
        for _, _, files in os.walk(directory)
        for f in files
        if f.endswith(".parquet")
    ) if os.path.isdir(directory) else 0


def _has_files(source: str, table: str) -> bool:
    directory = os.path.join(LANDING, source, table)
    if not os.path.isdir(directory):
        return False
    for _, _, files in os.walk(directory):
        if any(f.endswith(".parquet") for f in files):
            return True
    return False


def open_raw() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(RAW_DB)


def reset() -> None:
    """Delete the archive, the raw database and all pipeline state.

    The nuclear option, and useful precisely because the design makes it safe:
    everything here is reproducible from the source systems.
    """
    for path in (LANDING, RAW_DB, DLT_HOME):
        if os.path.isdir(path):
            shutil.rmtree(path)
        elif os.path.exists(path):
            os.remove(path)
