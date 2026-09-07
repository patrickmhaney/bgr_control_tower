#!/usr/bin/env python
"""Run the ingestion pipeline: source systems -> landing -> raw.

    python run_ingestion.py                    # all five sources
    python run_ingestion.py sage_x3 hubspot    # named sources
    python run_ingestion.py --full-refresh     # ignore watermarks
    python run_ingestion.py --explain          # print the spec, run nothing
    python run_ingestion.py --reset            # drop archive + state

Then `dbt build` reads the raw schemas. `--explain` is the fastest way to see
what the extraction design actually commits to per table.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import time

from ingestion import pipeline
from ingestion.config import SOURCES, Strategy
from ingestion.simulators import paycom_sftp


def explain() -> None:
    for source in SOURCES.values():
        print(f"\n{'=' * 78}\n{source.system}\n{'=' * 78}")
        print(f"  access          {source.access}")
        print(f"  auth            {source.auth}")
        print(f"  change tracking {source.change_tracking}")
        print(f"\n  {'table':30} {'strategy':15} {'disposition':12} "
              f"{'deletes':8} key")
        print("  " + "-" * 82)
        for spec in source.tables:
            key = ", ".join(spec.primary_key) or "-"
            deletes = ("reconcile" if spec.reconcile_keys != "never"
                       else "replaced")
            print(f"  {spec.name:30} {spec.strategy.value:15} "
                  f"{spec.write_disposition:12} {deletes:8} {key}")
            if spec.note:
                for line in _wrap(spec.note, 66):
                    print(f"      {line}")
        weekly = [t.name for t in source.tables if t.reconcile_keys != "never"]
        if weekly:
            print(f"\n  Deletes: {len(weekly)} of {len(source.tables)} tables use merge "
                  f"disposition, which never removes a row. A row hard-deleted\n"
                  f"  upstream persists in the warehouse until a key reconciliation "
                  f"runs. Not built yet - see docs/ingestion.md section 8.")

        if source.pitfalls:
            print("\n  Pitfalls")
            for pitfall in source.pitfalls:
                lines = _wrap(pitfall, 70)
                print(f"    - {lines[0]}")
                for line in lines[1:]:
                    print(f"      {line}")


def _wrap(text: str, width: int) -> list[str]:
    import textwrap
    return textwrap.wrap(" ".join(text.split()), width)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sources", nargs="*", default=None,
                        help=f"sources to run; default all of {sorted(SOURCES)}")
    parser.add_argument("--full-refresh", action="store_true",
                        help="ignore stored watermarks and read everything")
    parser.add_argument("--explain", action="store_true",
                        help="print the extraction spec and exit")
    parser.add_argument("--state", action="store_true",
                        help="show the stored watermarks and the landing archive, run nothing")
    parser.add_argument("--reset", action="store_true",
                        help="delete the landing archive, raw database and state")
    args = parser.parse_args()

    if args.explain:
        explain()
        return 0

    if args.state:
        marks = pipeline.watermarks()
        print(f"\nwatermarks  ({len(marks)} stored)")
        if not marks:
            print("  none yet - the next run is a full backfill")
        for source, table, mark in sorted(marks):
            spec = next((t for t in SOURCES[source].tables if t.name == table), None)
            lookback = f"minus {spec.lookback_days}d lookback" if spec else ""
            print(f"  {source:12} {table:16} {mark}   {lookback}")
        print("\nsources with no watermark - these read everything, every run")
        for source in SOURCES.values():
            stored = {t for s, t, _ in marks if s == source.name}
            without = [t.name for t in source.tables if t.name not in stored]
            if without:
                print(f"  {source.name:12} {len(without):>2} of {len(source.tables):>2} tables"
                      f"   {', '.join(without[:6])}{' ...' if len(without) > 6 else ''}")
        print(f"\nlanding archive")
        for source in SOURCES:
            files = pipeline.landed_files(source)
            if files:
                print(f"  {source:12} {files:>4} parquet file(s)")
        print(f"\n  {pipeline.LANDING}")
        return 0

    if args.reset:
        pipeline.reset()
        print("landing archive, raw database and pipeline state removed")
        return 0

    chosen = args.sources or list(SOURCES)
    unknown = [s for s in chosen if s not in SOURCES]
    if unknown:
        print(f"unknown source(s) {unknown}; available: {sorted(SOURCES)}", file=sys.stderr)
        return 1

    today = dt.date.today()
    if "paycom" in chosen:
        # Stands in for Paycom's Report Center writing to the SFTP drop. In
        # production this has already happened, on Paycom's schedule, and the
        # extractor's job is to notice if it has not.
        delivered = paycom_sftp.deliver_reports(today)
        print(f"[paycom]   {len(delivered)} scheduled report(s) delivered to the SFTP drop")

    print(f"\n{'source':12} {'tables':>7} {'rows read':>11} {'seconds':>9}")
    print("-" * 43)
    extracted = 0
    for name in chosen:
        started = time.time()
        _, counts = pipeline.extract(name, full_refresh=args.full_refresh, as_of=today)
        elapsed = time.time() - started
        rows = sum(counts.values())
        extracted += rows
        print(f"{name:12} {len(SOURCES[name].tables):>7} {rows:>11,} {elapsed:>9.1f}")
    print(f"{'extracted':12} {'':>7} {extracted:>11,}")

    print("\nprojecting landing -> raw")
    con = pipeline.open_raw()
    drift = []
    try:
        grand = 0
        for name in chosen:
            built = pipeline.project_landing_to_raw(con, name)
            n = sum(c for _, c in built)
            grand += n
            print(f"  raw.{name:<12} {len(built):>2} tables  {n:>9,} rows")
            drift.extend(pipeline.check_drift(con, name))
    finally:
        con.close()
    print(f"  {'total':<16} {'':>2}          {grand:>9,} rows")

    print("\nschema contract")
    if not drift:
        print("  no drift - every table matches ingestion/schema_contract.json")
    else:
        for d in drift:
            marker = "INCIDENT" if d.is_incident else "notice  "
            print(f"  {marker}  {d.describe()}")
        if any(d.is_incident for d in drift):
            print("\n  A lost column breaks something downstream. Do not regenerate the\n"
                  "  contract to make this pass - find out why the column disappeared.")
            return 2
    print(f"\nraw database: {pipeline.RAW_DB}")
    print("next: dbt build")
    return 0


if __name__ == "__main__":
    sys.exit(main())
