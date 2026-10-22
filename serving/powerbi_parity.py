"""Power BI parity: the golden answers, read from dashboard_cube through the measure templates.

    python -m serving.powerbi_parity write      # powerbi/parity/parity_queries.json
    python -m serving.powerbi_parity local      # the templates' SQL twin over marts.dashboard_cube
    python -m serving.powerbi_parity run        # the DAX against a deployed model (see below)

`write` maps every golden answer it can to a cube: one that holds all its
metrics at a grain it can roll up from (a coarser or equal grain for sums and
ratios, exactly that grain for fixed metrics). It writes the DAX query a
visual would run, with the frozen answer beside it.

`local` runs the same queries with the SQL twin of each template
(serving.powerbi.SQL) over the materialised cube. It proves, without Power
BI, that the cube plus the templates reproduce MetricFlow's golden answers -
rollups included. `run` sends the DAX to the Power BI REST API's
executeQueries endpoint, which proves the deployed model does the same.

`run` reads PBI_WORKSPACE_ID, PBI_DATASET_ID and PBI_ACCESS_TOKEN (a token for
https://analysis.windows.net/powerbi/api; CI gets it through its Azure
federated identity). It runs in the test environment after each deployment.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

import duckdb
import yaml

from core.settings import ROOT, settings
from evaluation.golden import GOLDEN, _maps_equal, _rows_to_map
from serving.powerbi import TABLE, Cube, measure_sql

OUT = os.path.join(ROOT, "powerbi", "parity", "parity_queries.json")


def _pick_cube(cube: Cube, metrics: list[str], group_by: list[str]) -> str | None:
    fits = []
    for name, c in cube.cubes.items():
        if not set(metrics) <= set(c["metrics"]) or not set(group_by) <= set(c["dims"]):
            continue
        if any(cube.rollups[m]["kind"] == "fixed" for m in metrics) and set(group_by) != set(c["dims"]):
            continue
        fits.append((len(c["dims"]), name))
    return min(fits)[1] if fits else None


def write() -> list[dict]:
    cube = Cube()
    with open(GOLDEN) as fh:
        doc = yaml.safe_load(fh)
    out = []
    for q in doc["queries"]:
        if "expect_refusal" in q or q.get("where"):
            continue
        group_by = q.get("group_by") or []
        name = _pick_cube(cube, q["metrics"], group_by)
        if name is None:
            continue
        cols = [f"'{TABLE}'[{cube.names[g]}]" for g in group_by]
        measures = [f'"{m}", [{cube.label(m)}]' for m in q["metrics"]]
        dax = (f"EVALUATE SUMMARIZECOLUMNS({', '.join(cols)}{', ' if cols else ''}"
               f"TREATAS({{\"{name}\"}}, '{TABLE}'[Cube]), {', '.join(measures)})")
        expected = (q.get("expected_by_provider", {}).get(settings.mdm_provider)
                    if q.get("mdm_sensitive") else q.get("expected"))
        out.append({"id": q["id"], "cube": name, "group_by": group_by, "metrics": q["metrics"],
                    "dax": dax, "expected": expected})
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(out, fh, indent=2, default=str)
        fh.write("\n")
    print(f"{len(out)} parity queries -> {OUT}")
    return out


def _compare(got: dict, q: dict) -> str | None:
    # SUMMARIZECOLUMNS leaves out a row whose measures are all blank; so does this.
    exp = {row[0]: row[1:] for row in q["expected"] or []}
    got, exp = ({k: v for k, v in m.items() if any(x is not None for x in v)} for m in (got, exp))
    return _maps_equal(got, exp, 1e-6)


def local() -> list[str]:
    """Every parity query through the SQL twin of the templates; the problems found."""
    cube = Cube()
    with open(OUT) as fh:
        queries = json.load(fh)
    problems = []
    con = duckdb.connect(settings.warehouse_path, read_only=True)
    try:
        for q in queries:
            dims = [f'"{g}"' for g in q["group_by"]]
            exprs = [measure_sql(m, cube.rollups[m]) for m in q["metrics"]]
            sql = (f"select {', '.join(dims + exprs)} from marts.{TABLE} where _cube = ?"
                   + (f" group by {', '.join(dims)}" if dims else ""))
            got = _rows_to_map(con.execute(sql, [q["cube"]]).fetchall(), len(dims))
            problem = _compare(got, q)
            print(f"{'ok  ' if problem is None else 'FAIL'} {q['id']} ({q['cube']})"
                  + (f": {problem}" if problem else ""))
            if problem:
                problems.append(f"{q['id']}: {problem}")
    finally:
        con.close()
    return problems


def run() -> int:
    ws, ds, token = (os.environ.get(k) for k in ("PBI_WORKSPACE_ID", "PBI_DATASET_ID",
                                                  "PBI_ACCESS_TOKEN"))
    if not (ws and ds and token):
        print("Set PBI_WORKSPACE_ID, PBI_DATASET_ID and PBI_ACCESS_TOKEN to run parity.")
        return 2
    with open(OUT) as fh:
        queries = json.load(fh)
    url = f"https://api.powerbi.com/v1.0/myorg/groups/{ws}/datasets/{ds}/executeQueries"
    failures = 0
    for q in queries:
        body = json.dumps({"queries": [{"query": q["dax"]}],
                           "serializerSettings": {"includeNulls": True}}).encode()
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            rows = json.load(resp)["results"][0]["tables"][0]["rows"]
        got = _rows_to_map([list(r.values()) for r in rows], len(q["group_by"]))
        problem = _compare(got, q)
        print(f"{'ok  ' if problem is None else 'FAIL'} {q['id']}" + (f": {problem}" if problem else ""))
        failures += problem is not None
    return 1 if failures else 0


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "write"
    if mode == "run":
        sys.exit(run())
    if mode == "local":
        sys.exit(1 if local() else 0)
    write()
