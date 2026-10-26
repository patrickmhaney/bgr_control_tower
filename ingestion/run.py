"""Extract one or all sources into the bronze changelog.

    python -m ingestion.run                         # every source
    python -m ingestion.run --source sage_x3
    python -m ingestion.run --source hubspot --reconcile
    python -m ingestion.run --full-refresh          # snapshot everything again
    python -m ingestion.run --freeze-schemas        # accept today's columns as the contract

Contract C2 is enforced here. Each source's columns are frozen in the
project pack's ingestion/schemas/<source>.schema.yaml: a new column fails the run, which is
how a silently changed source becomes a reviewed change instead of a wrong
number. `--freeze-schemas` re-exports the files; review the diff before
committing it, because re-freezing is also how a lost column gets silenced.
"""
from __future__ import annotations

import argparse
import os

import dlt

from core import project
from core.settings import settings

from .sources import BUILDERS

FROZEN = {"tables": "evolve", "columns": "freeze", "data_type": "freeze"}


def _configure() -> None:
    # `direct` keeps source column names exactly as they arrive (ITMREF_0, not
    # itmref_0). Bronze records what the source sent.
    os.environ["SCHEMA__NAMING"] = "direct"
    os.environ["DESTINATION__FILESYSTEM__BUCKET_URL"] = settings.bronze_root
    account = settings.get("storage_account")
    if account:
        # No key: the container's managed identity is picked up by default.
        os.environ["DESTINATION__FILESYSTEM__CREDENTIALS__AZURE_STORAGE_ACCOUNT_NAME"] = account
    # Table names here never contain "/", so the default layout is safe.
    os.environ["DESTINATION__FILESYSTEM__WARN_UNSAFE_LAYOUT_SEPARATORS"] = "false"
    os.environ.setdefault("RUNTIME__LOG_LEVEL", "WARNING")
    os.makedirs(settings.data_dir, exist_ok=True)


def extract(source: str, full_refresh: bool = False, reconcile: bool = False,
            freeze_schemas: bool = False, tables: list[str] | None = None) -> dict[str, int]:
    """Run one source's extract. Returns rows written per table in this run."""
    _configure()
    schema_dir = project.current().schemas
    schema_file = os.path.join(schema_dir, f"{source}.schema.yaml")
    frozen = os.path.exists(schema_file) and not freeze_schemas
    pipeline = dlt.pipeline(
        pipeline_name=f"bronze_{source}",
        pipelines_dir=os.path.join(settings.data_dir, "dlt"),
        destination="filesystem",
        dataset_name=source,
        import_schema_path=schema_dir if frozen else None,
        export_schema_path=schema_dir if (freeze_schemas or not frozen) else None,
        progress=None,
    )
    kwargs = {"full_refresh": full_refresh, "tables": tables}
    if source == "hubspot":
        kwargs["reconcile"] = reconcile
    pipeline.run(BUILDERS[source](**kwargs), schema_contract=FROZEN if frozen else "evolve")
    if not frozen:
        _strip_processing_hints(schema_file)
    info = pipeline.last_trace.last_normalize_info
    counts = dict(info.row_counts) if info else {}
    return {t: n for t, n in counts.items() if not t.startswith("_dlt")}


def _strip_processing_hints(path: str) -> None:
    """Drop dlt's per-dataset bookkeeping so the file is a pure column contract."""
    import yaml

    if not os.path.exists(path):
        return
    with open(path) as fh:
        schema = yaml.safe_load(fh)
    for table in schema.get("tables", {}).values():
        table.pop("x-normalizer", None)
    schema.get("tables", {}).pop("_dlt_pipeline_state", None)
    with open(path, "w") as fh:
        yaml.safe_dump(schema, fh, sort_keys=False)


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m ingestion.run", description=__doc__.split("\n")[0])
    p.add_argument("--source", choices=sorted(BUILDERS), action="append",
                   help="repeatable; default is every source")
    p.add_argument("--full-refresh", action="store_true")
    p.add_argument("--reconcile", action="store_true",
                   help="also diff HubSpot keys against the source to catch hard deletes")
    p.add_argument("--freeze-schemas", action="store_true")
    args = p.parse_args()
    for source in args.source or [s for s in BUILDERS if s in project.current().systems]:
        counts = extract(source, args.full_refresh, args.reconcile, args.freeze_schemas)
        total = sum(counts.values())
        print(f"{source:<12} {total:>8,} rows  " +
              ", ".join(f"{t}={n}" for t, n in sorted(counts.items()) if n))


if __name__ == "__main__":
    main()
