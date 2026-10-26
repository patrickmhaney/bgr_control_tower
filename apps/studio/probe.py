"""What a step did, and whether its boundary held.

    python -m apps.studio.probe <step>      # prints one JSON object

The Studio runs this in its own process after each step, so the web server
never holds a database open while the pipeline writes. Every check here is
the platform's own: the same functions the conformance tests and CI call.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import os
import subprocess
import sys

import duckdb
import yaml

from core import project
from core.settings import ROOT, settings

#: The run screen's headline numbers and fact tables when a pack has them;
#: otherwise the company cube's first metrics that roll up, and its first facts.
HEADLINE = ["on_time_delivery_rate", "order_fill_rate", "revenue", "match_rate",
            "inventory_accuracy", "win_rate"]
FACTS = {"fct_sales_order_line": "Order lines", "fct_delivery_line": "Delivery lines",
         "fct_invoice_line": "Invoice lines", "fct_deal": "Deals"}


def _fact(label, raw, fmt="int", better=None, value=None):
    return {"label": label, "raw": raw, "fmt": fmt, "better": better, "value": value}


def _today() -> dt.date:
    from sources import clock

    return clock.status()["today"]


def _golden() -> dict:
    with open(project.current().golden) as fh:
        return yaml.safe_load(fh)


def _frozen_applies() -> bool:
    """The frozen answers hold only for the sources as of `as_of`."""
    return _today().isoformat() == str(_golden()["as_of"])


def _quiet(fn, *args, **kwargs):
    """Run a platform function that prints per-item lines; return (result, lines)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        result = fn(*args, **kwargs)
    return result, buf.getvalue().splitlines()


def _run_results() -> dict:
    with open(os.path.join(project.current().target, "run_results.json")) as fh:
        results = json.load(fh)["results"]
    out = {"models": 0, "seeds": 0, "tests": 0, "passed": 0, "warned": 0, "failed": 0}
    for r in results:
        kind = r["unique_id"].split(".")[0]
        if kind in ("model", "seed"):
            out[kind + "s"] += 1
        elif kind == "test":
            out["tests"] += 1
            out[{"pass": "passed", "warn": "warned"}.get(r["status"], "failed")] += 1
        if r["status"] in ("error", "fail"):
            out["failed"] += kind != "test"
    return out


def _check(cid, title, passed, facts=(), problems=(), test=None):
    return {"id": cid, "title": title, "passed": bool(passed), "facts": list(facts),
            "problems": list(problems)[:8], "test": test}


# ------------------------------------------------------------------ steps --
def day() -> dict:
    today = _today()
    con = duckdb.connect(settings.mock_db, read_only=True)
    try:
        def n(sql):
            return con.execute(sql, [today]).fetchone()[0]

        def on(col):
            return f"try_cast(substr(cast({col} as varchar), 1, 10) as date) = ?"

        facts = [
            _fact("Sales orders", n(f"select count(*) from sage_x3.SORDER where {on('ORDDAT_0')}")),
            _fact("Deliveries", n(f"select count(*) from sage_x3.SDELIVERY where {on('SHIDAT_0')}")),
            _fact("Invoices", n(f"select count(*) from sage_x3.SINVOICEV where {on('INVDAT_0')}")),
            _fact("New HubSpot deals", n(f"select count(*) from hubspot.deal where {on('createdate')}")),
        ]
    finally:
        con.close()
    return {"facts": facts, "checks": []}


def collect() -> dict:
    from ingestion.verify import compare

    con = duckdb.connect()
    con.execute("install delta; load delta")
    root = os.path.join(settings.bronze_root, "sage_x3")
    scans = " union all ".join(f"select _op, _dlt_load_id from delta_scan('{os.path.join(root, t)}')"
                               for t in sorted(os.listdir(root))
                               if os.path.isdir(os.path.join(root, t, "_delta_log")))
    # Only what this run loaded: dlt load ids are the load's start time.
    since = float(os.environ.get("STUDIO_SINCE", "0"))
    ops = dict(con.execute(f"with c as ({scans}) select _op, count(*) from c "
                           "where cast(_dlt_load_id as double) >= ? group by 1", [since]).fetchall())
    con.close()
    facts = []
    if ops.get("S"):
        facts.append(_fact("X3 snapshot rows", ops["S"]))
    facts += [_fact("X3 inserts (CDC)", ops.get("I", 0)),
              _fact("X3 updates (CDC)", ops.get("U", 0)),
              _fact("X3 deletes (CDC)", ops.get("D", 0))]

    tables = compare()
    bad = [t for t in tables if t["missing"] or t["extra"]]
    check = _check(
        "C2", "Raw history matches the source tables", not bad,
        [_fact("Tables matching", len(tables) - len(bad), value=f"{len(tables) - len(bad)} of {len(tables)}"),
         _fact("Rows compared", sum(t["rows"] for t in tables))],
        [f"{t['source']}.{t['table']}: {t['missing']} rows missing, {t['extra']} extra" for t in bad],
        "tests/conformance/test_ingestion_convergence.py")
    return {"facts": facts, "checks": [check]}


def clean() -> dict:
    r = _run_results()
    check = _check(
        "quality", "Staging data tests", r["failed"] == 0,
        [_fact("Tests passed", r["passed"]), _fact("Warnings", r["warned"])],
        [f"{r['failed']} tests or models failed (see log)"] if r["failed"] else [],
        "dbt tests in transform/platform/models/silver/staging")
    return {"facts": [_fact("Staging tables built", r["models"]), _fact("Seeds loaded", r["seeds"])],
            "checks": [check]}


def match() -> dict:
    from mdm.run import score_against_truth, validate

    with open(os.path.join(settings.data_dir, "mdm_quality.json")) as fh:
        quality = json.load(fh)
    con = duckdb.connect()
    con.execute("install delta; load delta")
    tables = {}
    for name in ("mdm_xref", "mdm_golden_customer", "mdm_golden_employee"):
        cur = con.execute(f"select * from delta_scan('{settings.bronze_root}/mdm/{name}')")
        cols = [d[0] for d in cur.description]
        tables[name] = [dict(zip(cols, row)) for row in cur.fetchall()]
    con.close()
    problems = []
    try:
        validate(tables)
    except Exception as exc:  # noqa: BLE001 - the contract's own message is the finding
        problems.append(str(exc))
    golden = {g["golden_key"] for t in ("mdm_golden_customer", "mdm_golden_employee") for g in tables[t]}
    orphans = sum(1 for x in tables["mdm_xref"] if x["golden_key"] not in golden)
    if orphans:
        problems.append(f"{orphans} source records point at no golden record")
    score = score_against_truth(tables["mdm_xref"]) or {}
    if score and min(score["precision"], score["recall"]) < 0.8:
        problems.append("match quality is below the 80% floor")
    provider = {"splink": "Splink (probabilistic)", "rules": "Rules matcher"}[quality["provider"]]
    facts = [_fact("Matcher", None, "text", value=provider),
             _fact("Golden customers", len(tables["mdm_golden_customer"])),
             _fact("HubSpot companies matched to X3", quality["customer_links"]),
             _fact("Matches flagged for review", quality["needs_review"], better="down")]
    check = _check(
        "C3", "Golden ID coverage and match quality", not problems,
        [_fact("Match precision", score.get("precision"), "percent", "up"),
         _fact("Match recall", score.get("recall"), "percent", "up")],
        problems, "tests/conformance/test_mdm_contract.py")
    return {"facts": facts, "checks": [check]}


def model() -> dict:
    r = _run_results()
    with open(project.current().manifest) as fh:
        nodes = json.load(fh)["nodes"].values()
    gold = [n for n in nodes if n["resource_type"] == "model" and n["schema"].endswith("gold")]
    enforced = [n for n in gold if n["config"].get("contract", {}).get("enforced")]
    con = duckdb.connect(settings.warehouse_path, read_only=True)
    try:
        def rows(t):
            return con.execute(f"select count(*) from gold.{t}").fetchone()[0]

        names = [n["name"] for n in gold if n["name"].startswith("fct_")]
        chosen = [f for f in FACTS if f in names] + sorted(f for f in names if f not in FACTS)
        facts = [_fact(FACTS.get(f) or f.removeprefix("fct_").replace("_", " ").capitalize() + "s", rows(f))
                 for f in chosen[:4]]
    finally:
        con.close()
    check = _check(
        "C4", "Gold table contracts and tests",
        r["failed"] == 0 and len(enforced) == len(gold),
        [_fact("Tables under contract", len(enforced), value=f"{len(enforced)} of {len(gold)}"),
         _fact("Columns with enforced types", sum(len(n["columns"]) for n in enforced)),
         _fact("Tests passed", r["passed"])],
        [f"{r['failed']} tests or models failed (see log)"] if r["failed"] else [],
        "enforced contracts in the pack's models/gold/_gold__models.yml")
    return {"facts": facts, "checks": [check]}


def metrics() -> dict:
    from evaluation.golden import run as golden_run
    from semantic.lint import lint
    from serving.powerbi import Cube, measure_sql
    from serving.powerbi_parity import local

    with open(project.current().semantic_manifest) as fh:
        meta = {m["name"]: {"label": m["label"], **((m.get("config") or {}).get("meta") or {})}
                for m in json.load(fh)["metrics"]}
    fmt = {"percent": "percent", "currency_usd": "usd", "days": "days"}
    cube = Cube()
    rollups, label = cube.rollups, cube.label
    year = _today().replace(month=1, day=1)
    company = cube.cubes["mart_company_monthly"]["metrics"]
    headline = [m for m in HEADLINE if m in company]
    headline = (headline + [m for m in company if m not in headline and rollups[m]["kind"] != "fixed"])[:6]
    con = duckdb.connect(settings.warehouse_path, read_only=True)
    try:
        # Year to date, rolled up from the monthly cube with the Power BI templates' own math.
        exprs = ", ".join(measure_sql(m, rollups[m]) for m in headline)
        row = con.execute(f"select {exprs} from marts.dashboard_cube "
                          "where _cube = 'mart_company_monthly' and metric_time__month >= ?",
                          [year]).fetchone()
        cube_rows = con.execute("select count(*) from marts.dashboard_cube").fetchone()[0]
        cube_cols = len(con.execute("select * from marts.dashboard_cube limit 0").description)
    finally:
        con.close()
    facts = [_fact(f"{label(m)}, {year:%Y} to date", float(v) if v is not None else None,
                   fmt.get(meta[m].get("format"), "int"),
                   {"higher_is_better": "up", "lower_is_better": "down"}.get(meta[m].get("direction")))
             for m, v in zip(headline, row)]
    facts.append(_fact("Power BI table size", cube_rows, value=f"{cube_rows:,} × {cube_cols}"))

    frozen = _frozen_applies()
    failures, lines = _quiet(golden_run, "check", frozen=frozen)
    results = [ln for ln in lines if ln.startswith(("ok  ", "FAIL"))]
    passed = sum(ln.startswith("ok") for ln in results)
    issues = lint()
    how = ("semantic layer, reference SQL and frozen answer" if frozen else
           "semantic layer and reference SQL (frozen answers apply to day 0)")
    c5 = _check("C5", "Golden answers", failures == 0 and not issues,
                [_fact("Passing", passed, value=f"{passed} of {len(results)}"),
                 _fact("Compared", None, "text", value=how),
                 _fact("Lint violations", len(issues), better="down")],
                [ln[5:] for ln in results if ln.startswith("FAIL")] + issues,
                "tests/conformance/test_golden_answers.py")

    problems, _ = _quiet(local, live=not frozen)
    with open(project.current().parity_queries) as fh:
        total = len(json.load(fh))
    c7 = _check("C7", "Power BI measure parity", not problems,
                [_fact("Parity queries passing", total - len(problems),
                       value=f"{total - len(problems)} of {total}"),
                 _fact("Measure templates", 3)],
                problems, "tests/conformance/test_dashboard_cube.py")
    return {"facts": facts, "checks": [c5, c7]}


def serve() -> dict:
    con = duckdb.connect(settings.serving_url, read_only=True) if settings.serving_destination == "duckdb" \
        else None
    facts = []
    if con:
        try:
            tables = con.execute("select table_name, estimated_size from duckdb_tables() "
                                 "where schema_name = 'marts' and table_name not like '\\_dlt%' escape '\\'"
                                 ).fetchall()
        finally:
            con.close()
        facts = [_fact("Tables in the serving database", len(tables)),
                 _fact("Rows served", sum(n for _, n in tables))]
    # The API and MCP contract test itself, exactly as CI runs it.
    out = subprocess.run([sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider",
                          "tests/conformance/test_data_service.py"],
                         cwd=ROOT, capture_output=True, text=True)
    summary = (out.stdout.strip().splitlines() or [""])[-1]
    passed = int(summary.split(" passed")[0].split()[-1]) if " passed" in summary else 0
    from apps.data_service import mcp_server
    from apps.data_service.app import app

    with open(mcp_server.__file__) as fh:
        tools = fh.read().count("@mcp.tool()")
    routes = {getattr(r, "path", "") for r in app.routes}
    check = _check("C6", "API and MCP contract tests", out.returncode == 0,
                   [_fact("Contract tests passed", passed),
                    _fact("API endpoints", len({p for p in routes if not p.startswith(("/docs", "/openapi",
                                                                                           "/redoc", "/mcp"))})),
                    _fact("MCP tools", tools)],
                   [] if out.returncode == 0 else out.stdout.strip().splitlines()[-8:],
                   "tests/conformance/test_data_service.py")
    return {"facts": facts, "checks": [check]}


PROBES = {f.__name__: f for f in (day, collect, clean, match, model, metrics, serve)}


if __name__ == "__main__":
    print(json.dumps(PROBES[sys.argv[1]](), default=str))
