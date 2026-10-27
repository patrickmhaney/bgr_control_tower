"""Step commands: every step of the platform, runnable on its own.

    python -m ctl [--project SLUG] <step> ...   project pack (default sample_v2, or CT_PROJECT)
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
    python -m ctl check-pack       the pack fills the fixed slots only (core/pack.py)
    python -m ctl requirements [--regenerate]   check requirements/; rewrite the files generated from it
    python -m ctl preview [--changed PATH ...]   rebuild what compiled requirements changed
    python -m ctl kpis             each KPI's latest full month and the one before, as JSON

Dagster calls these same functions; nothing in orchestration/ holds logic of
its own (rule 1 in PLAN.md §9.3). Any other orchestrator - ADF, a Boomi Logic
Flow, Snowflake Tasks, cron - could call them instead.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import os
import shutil
import subprocess
import sys

from core import project
from core.settings import settings

#: Commands that write the warehouse, raw storage or dbt's target folder. They
#: hold the pipeline lock (core/lock.py), so two runs never overlap.
WRITES = {"sources", "ingest", "dbt", "mdm", "build", "materialize", "serve-load", "run", "reset", "preview"}

#: Everything dbt must build before MDM can run: bronze, staging, seeds. Tags
#: come from the layer config, so they select the platform's staging adapters too.
BEFORE_MDM = {"raw": "tag:bronze", "clean": "tag:staging resource_type:seed"}
PRE_MDM = " ".join(BEFORE_MDM.values())
#: The build in order; `--stage` runs one of them.
STAGES = ("raw", "clean", "mdm", "model")


def dbt(*args: str, check: bool = True) -> int:
    env = {**os.environ, **settings.dbt_env()}
    exe = os.path.join(os.path.dirname(sys.executable), "dbt")
    if not os.path.exists(exe):
        exe = shutil.which("dbt") or "dbt"
    cwd = project.current().dbt_dir
    if not os.path.isdir(os.path.join(cwd, "dbt_packages")) and args[:1] != ("deps",):
        subprocess.run([exe, "deps", "--quiet"], cwd=cwd, env=env, check=True)
    result = subprocess.run([exe, *args], cwd=cwd, env=env)
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

    for source in project.current().systems:
        counts = extract(source, reconcile=reconcile)
        print(f"ingest {source:<11} {sum(counts.values()):>8,} rows")
    build()
    materialize()
    load_serving()


def preview(changed: list[str]) -> None:
    """Rebuild after the requirements tool compiled new "what" files into the pack.

    A pack never built gets the whole pipeline. Otherwise only what the files
    touch: the changed seeds and everything downstream of them, then the
    semantic manifest, the governance lint and the cubes. Gold is never
    rebuilt for a requirements change, because requirements never change SQL.
    """
    from semantic.lint import lint
    from serving.materialize import materialize
    from serving.reverse_load import load_serving
    from sources import clock

    if not os.path.exists(settings.warehouse_path):
        if not os.path.exists(settings.mock_db):
            clock.init()
        run_all()
        return
    seeds = sorted({os.path.splitext(os.path.basename(c))[0] for c in changed
                    if c.startswith("seeds/") and c.endswith(".csv")})
    if seeds:
        dbt("build", "--select", *[f"{s}+" for s in seeds], "--indirect-selection", "buildable")
    # A full parse: partial parsing reorders the manifest, and the generated files follow its order.
    dbt("parse", "--quiet", "--no-partial-parse")
    problems = lint()
    for p in problems:
        print(f"lint: {p}")
    if problems:
        raise SystemExit(f"lint: {len(problems)} problem(s) - the preview stops here")
    materialize()
    load_serving()


def kpis() -> list[dict]:
    """Each KPI in the company cube: its latest full month and the month before."""
    import duckdb

    from serving.powerbi import Cube, measure_sql
    from sources import clock

    cube = Cube()
    company = cube.cubes.get("mart_company_monthly", {}).get("metrics", [])
    today = clock.status()["today"]
    month = (today.replace(day=1) - dt.timedelta(days=1)).replace(day=1)
    out = []
    con = duckdb.connect(settings.warehouse_path, read_only=True)
    try:
        for m in company:
            sql = (f"select metric_time__month, {measure_sql(m, cube.rollups[m])} from marts.dashboard_cube "
                   "where _cube = 'mart_company_monthly' and metric_time__month <= ? "
                   "group by 1 order by 1 desc limit 2")
            rows = con.execute(sql, [month]).fetchall()
            meta = cube.meta(m)
            out.append({"metric": m, "label": cube.label(m), "status": meta.get("status"),
                        "format": meta.get("format"), "direction": meta.get("direction"),
                        "month": rows[0][0].isoformat()[:10] if rows else None,
                        "value": float(rows[0][1]) if rows and rows[0][1] is not None else None,
                        "previous": float(rows[1][1]) if len(rows) > 1 and rows[1][1] is not None else None})
    finally:
        con.close()
    return out


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m ctl", description="Platform step commands.")
    p.add_argument("--project", help=f"project pack under projects/ (default {project.DEFAULT}, or CT_PROJECT)")
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
    c = sub.add_parser("check-pack")
    c.add_argument("slug", nargs="?", help="default: the project in use")
    rq = sub.add_parser("requirements")
    rq.add_argument("--regenerate", action="store_true",
                    help="rewrite seeds/process.csv and the open questions section from requirements/")
    pv = sub.add_parser("preview")
    pv.add_argument("--changed", nargs="*", default=[], help="pack files the compiler changed")
    sub.add_parser("kpis")
    a = p.parse_args()
    if a.project:
        project.use(a.project)

    from core.lock import PipelineBusy, held

    writes = a.cmd in WRITES and not (a.cmd == "sources" and a.action == "status")
    try:
        with held("python -m ctl " + " ".join(sys.argv[1:])) if writes else contextlib.nullcontext():
            _dispatch(a)
    except PipelineBusy as exc:
        raise SystemExit(str(exc)) from None


def _dispatch(a: argparse.Namespace) -> None:
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

        for source in a.source or [s for s in BUILDERS if s in project.current().systems]:
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

        # From a full parse: partial parsing reorders the manifest, and the files follow its order.
        dbt("parse", "--quiet", "--no-partial-parse")
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
    elif a.cmd == "preview":
        preview(a.changed)
    elif a.cmd == "kpis":
        import json

        print(json.dumps(kpis(), default=str))
    elif a.cmd == "check-pack":
        from core.pack import main as check_pack

        check_pack(a.slug or project.slug())
    elif a.cmd == "requirements":
        requirements(a.regenerate)
    elif a.cmd == "reset":
        if os.path.isdir(settings.data_dir):
            shutil.rmtree(settings.data_dir)
        print(f"Removed {settings.data_dir}")


def requirements(regenerate: bool) -> None:
    """Check a project's requirements/ (core/requirements). The Studio keeps the
    generated files in step on every save; --regenerate does it after an edit
    made by hand, for the engineer to commit with that edit."""
    from core import requirements as rq

    pack = project.current()
    if not os.path.isdir(pack.requirements):
        raise SystemExit(f"{pack.slug} has no requirements/ yet")
    if regenerate:
        for rel in rq.regenerate(pack):
            print(f"requirements: rewrote {rel}")
    problems = rq.check(pack)
    for p in problems:
        print(f"requirements: {p}")
    print("requirements: ok" if not problems else f"requirements: {len(problems)} problem(s)")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
