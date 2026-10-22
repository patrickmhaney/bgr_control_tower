"""Step commands: every step of the platform, runnable on its own.

    python -m ctl sources init | advance [--days N] | status
    python -m ctl ingest [--source S] [--full-refresh] [--reconcile]
    python -m ctl dbt <any dbt arguments>
    python -m ctl mdm [--provider splink|rules]
    python -m ctl build [--stage S]  dbt before MDM (raw, clean), MDM, dbt after MDM (model)
    python -m ctl materialize      saved queries -> cubes + dashboard_cube (DuckDB tables + Parquet)
    python -m ctl serve-load       marts -> the serving database (dlt reverse load)
    python -m ctl publish          copy the warehouse file to raw storage
    python -m ctl run              the daily pipeline: ingest, build, materialize, serve-load
    python -m ctl powerbi          regenerate the Power BI model and parity queries (files in git)
    python -m ctl reset            delete everything under the data directory

Dagster calls these same functions; nothing in orchestration/ holds logic of
its own (rule 1 in PLAN.md §9.3). Any other orchestrator - ADF, a Boomi Logic
Flow, Snowflake Tasks, cron - could call them instead.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

from core.settings import ROOT, settings

TRANSFORM = os.path.join(ROOT, "transform")

#: Everything dbt must build before MDM can run: bronze, staging, seeds.
BEFORE_MDM = {"raw": "path:models/bronze", "clean": "path:models/silver/staging path:seeds"}
PRE_MDM = " ".join(BEFORE_MDM.values())
#: The build in order; `--stage` runs one of them.
STAGES = ("raw", "clean", "mdm", "model")


def dbt(*args: str, check: bool = True) -> int:
    env = {**os.environ, **settings.dbt_env()}
    exe = os.path.join(os.path.dirname(sys.executable), "dbt")
    if not os.path.exists(exe):
        exe = shutil.which("dbt") or "dbt"
    if not os.path.isdir(os.path.join(TRANSFORM, "dbt_packages")):
        subprocess.run([exe, "deps", "--quiet"], cwd=TRANSFORM, env=env, check=True)
    result = subprocess.run([exe, *args], cwd=TRANSFORM, env=env)
    if check and result.returncode:
        raise SystemExit(result.returncode)
    return result.returncode


def build(provider: str | None = None, stages: tuple[str, ...] = STAGES) -> None:
    from mdm.run import run_mdm

    # Cautious: only tests whose every parent is in this step. Buildable: the
    # last step also runs tests that touch earlier models (an MDM output joined
    # to a seed), which excluding those models would otherwise drop.
    before = [path for s in ("raw", "clean") if s in stages for path in BEFORE_MDM[s].split()]
    if before:
        dbt("build", "--select", *before, "--indirect-selection", "cautious")
    if "mdm" in stages:
        run_mdm(provider)
    if "model" in stages:
        dbt("build", "--exclude", *PRE_MDM.split(), "--indirect-selection", "buildable")


def run_all(reconcile: bool = False) -> None:
    from ingestion.run import extract
    from serving.materialize import materialize
    from serving.reverse_load import load_serving

    for source in ("sage_x3", "hubspot", "netstock", "azure_cost"):
        counts = extract(source, reconcile=reconcile)
        print(f"ingest {source:<11} {sum(counts.values()):>8,} rows")
    build()
    materialize()
    load_serving()


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m ctl", description="Platform step commands.")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sources")
    s.add_argument("action", choices=["init", "advance", "status"])
    s.add_argument("--days", type=int, default=1)
    i = sub.add_parser("ingest")
    i.add_argument("--source", action="append")
    i.add_argument("--full-refresh", action="store_true")
    i.add_argument("--reconcile", action="store_true")
    i.add_argument("--freeze-schemas", action="store_true")
    d = sub.add_parser("dbt")
    d.add_argument("args", nargs=argparse.REMAINDER)
    m = sub.add_parser("mdm")
    m.add_argument("--provider", choices=["splink", "rules"])
    b = sub.add_parser("build")
    b.add_argument("--provider", choices=["splink", "rules"])
    b.add_argument("--stage", choices=STAGES, action="append")
    sub.add_parser("materialize")
    sub.add_parser("powerbi")
    sub.add_parser("serve-load")
    sub.add_parser("publish")
    r = sub.add_parser("run")
    r.add_argument("--reconcile", action="store_true")
    sub.add_parser("reset")
    a = p.parse_args()

    if a.cmd == "sources":
        from sources import clock

        if a.action == "init":
            clock.init()
            print(f"Sources initialised as of {clock.status()['today']}")
        elif a.action == "advance":
            for day, n in clock.advance(a.days):
                print(f"{day}: {n:,} change rows captured")
        else:
            for k, v in clock.status().items():
                print(f"{k:<24} {v}")
    elif a.cmd == "ingest":
        from ingestion.run import BUILDERS, extract

        for source in a.source or list(BUILDERS):
            counts = extract(source, a.full_refresh, a.reconcile, a.freeze_schemas)
            print(f"{source:<12} {sum(counts.values()):>8,} rows")
    elif a.cmd == "dbt":
        raise SystemExit(dbt(*a.args, check=False))
    elif a.cmd == "mdm":
        from mdm.run import run_mdm

        run_mdm(a.provider)
    elif a.cmd == "build":
        build(a.provider, tuple(a.stage or STAGES))
    elif a.cmd == "materialize":
        from serving.materialize import materialize

        materialize()
    elif a.cmd == "powerbi":
        from serving import powerbi_parity
        from serving.powerbi import generate_model

        generate_model()
        powerbi_parity.write()
    elif a.cmd == "serve-load":
        from serving.reverse_load import load_serving

        load_serving()
    elif a.cmd == "publish":
        from serving.publish import publish_warehouse

        publish_warehouse()
    elif a.cmd == "run":
        run_all(a.reconcile)
    elif a.cmd == "reset":
        if os.path.isdir(settings.data_dir):
            shutil.rmtree(settings.data_dir)
        print(f"Removed {settings.data_dir}")


if __name__ == "__main__":
    main()
