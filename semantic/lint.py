"""Governance lint: the rules review would otherwise have to remember.

    python -m semantic.lint          # exit 1 on any violation

Checks the compiled manifests (run `python -m ctl dbt parse` first):

* every KPI has an owner (TBD is allowed, and stays visible), a role, a status
  in {active, provisional}, and a provisional_reason when provisional
* every backlog metric is placeholder or blocked, with a reason
* every measure is an aggregation over a bare column - arithmetic goes in the fact
* every KPI is in at least one saved query, so a dashboard can show it
* every metric named in the dashboard seeds exists in the catalog
* every gold model has an enforced contract and an owner
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys

import yaml

from core.settings import ROOT

TARGET = os.path.join(ROOT, "transform", "target")
SEEDS = os.path.join(ROOT, "transform", "seeds")
AGGS = {"sum", "count", "count_distinct", "average", "min", "max"}
STATUSES = {"active", "provisional"}
BACKLOG_STATUSES = {"placeholder", "blocked"}
FORMATS = {"percent", "currency_usd", "days", "count"}


def lint() -> list[str]:
    errors: list[str] = []
    with open(os.path.join(TARGET, "semantic_manifest.json")) as fh:
        sm = json.load(fh)
    with open(os.path.join(TARGET, "manifest.json")) as fh:
        manifest = json.load(fh)
    with open(os.path.join(ROOT, "semantic", "backlog.yml")) as fh:
        backlog = yaml.safe_load(fh)["metrics"]
    in_cubes = {m for sq in sm.get("saved_queries", []) for m in sq["query_params"]["metrics"]}

    for s in sm["semantic_models"]:
        for ms in s.get("measures", []):
            if ms["agg"].lower() not in AGGS:
                errors.append(f"measure {ms['name']}: aggregation {ms['agg']!r} is not allowed")
            if not re.fullmatch(r"[a-z_][a-z0-9_]*", ms.get("expr") or ms["name"]):
                errors.append(f"measure {ms['name']}: expr must be a bare column - put arithmetic in the fact")

    names = set()
    for m in sm["metrics"]:
        names.add(m["name"])
        meta = (m.get("config") or {}).get("meta") or {}
        where = f"metric {m['name']}"
        if not meta.get("owner"):
            errors.append(f"{where}: owner is required (TBD is allowed)")
        if meta.get("role") not in ("kpi", "component"):
            errors.append(f"{where}: role must be kpi or component")
        if meta.get("status") not in STATUSES:
            errors.append(f"{where}: status must be one of {sorted(STATUSES)}")
        if meta.get("status") == "provisional" and not meta.get("provisional_reason"):
            errors.append(f"{where}: provisional needs a provisional_reason")
        if meta.get("format") and meta["format"] not in FORMATS:
            errors.append(f"{where}: format must be one of {sorted(FORMATS)}")
        if meta.get("role") == "kpi" and not (m.get("description") or "").strip():
            errors.append(f"{where}: a KPI needs a description")
        if meta.get("role") == "kpi" and m["name"] not in in_cubes:
            errors.append(f"{where}: a KPI must be in at least one saved query (a dashboard cube)")

    for b in backlog:
        names.add(b["name"])
        if b.get("status") not in BACKLOG_STATUSES:
            errors.append(f"backlog {b['name']}: status must be placeholder or blocked")
        reason = b.get("blocked_reason") if b.get("status") == "blocked" else b.get("placeholder_reason")
        if not reason:
            errors.append(f"backlog {b['name']}: a {b.get('status')} metric needs its reason")
        if not b.get("owner"):
            errors.append(f"backlog {b['name']}: owner is required (TBD is allowed)")

    for seed in ("process_metric.csv", "department_metric.csv"):
        with open(os.path.join(SEEDS, seed)) as fh:
            for row in csv.DictReader(fh):
                if row["metric_name"] not in names:
                    errors.append(f"{seed}: {row['metric_name']!r} is not in the metric catalog")

    for node in manifest["nodes"].values():
        if node["resource_type"] != "model" or node["config"].get("schema") != "gold":
            continue
        if not node["config"].get("contract", {}).get("enforced"):
            errors.append(f"gold model {node['name']}: contract must be enforced (C4)")
        if not (node["config"].get("meta") or {}).get("owner"):
            errors.append(f"gold model {node['name']}: meta.owner is required")
    return errors


def main() -> None:
    errors = lint()
    for e in errors:
        print(f"lint: {e}")
    print("lint: ok" if not errors else f"lint: {len(errors)} problem(s)")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
