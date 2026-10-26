"""Governance lint: the rules review would otherwise have to remember.

    python -m semantic.lint          # exit 1 on any violation

Checks the compiled manifests (run `python -m ctl dbt parse` first):

* every KPI has an owner (TBD is allowed, and stays visible), a role, a status
  in {active, provisional}, and a provisional_reason when provisional
* every backlog metric is placeholder or blocked, with a reason
* every measure is an aggregation over a bare column - arithmetic goes in the fact
* every KPI is in at least one saved query, so a dashboard can show it
* every metric named in the dashboard seeds exists in the catalog
* metric labels are unique within the project, backlog included (dbt already
  rejects a duplicate name; nothing else stops two metrics both called "$ Sales")
* a metric's meta uses only the governance keys; `requirement` traces it to the
  dashboard slot that asked for it (e.g. O2C-M1, contract C8)
* every gold model has an enforced contract and an owner
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys

import yaml

from core import project

AGGS = {"sum", "count", "count_distinct", "average", "min", "max"}
STATUSES = {"active", "provisional"}
BACKLOG_STATUSES = {"placeholder", "blocked"}
FORMATS = {"percent", "currency_usd", "days", "count"}
META_KEYS = {"role", "status", "owner", "owner_proposed", "provisional_reason", "caveats", "format",
             "direction", "is_data_quality", "requirement"}
REQUIREMENT = re.compile(r"[A-Z0-9]+-M[1-9][0-9]*")


def lint() -> list[str]:
    errors: list[str] = []
    pack = project.current()
    with open(pack.semantic_manifest) as fh:
        sm = json.load(fh)
    with open(pack.manifest) as fh:
        manifest = json.load(fh)
    with open(pack.backlog) as fh:
        backlog = yaml.safe_load(fh)["metrics"]
    in_cubes = {m for sq in sm.get("saved_queries", []) for m in sq["query_params"]["metrics"]}

    for s in sm["semantic_models"]:
        for ms in s.get("measures", []):
            if ms["agg"].lower() not in AGGS:
                errors.append(f"measure {ms['name']}: aggregation {ms['agg']!r} is not allowed")
            if not re.fullmatch(r"[a-z_][a-z0-9_]*", ms.get("expr") or ms["name"]):
                errors.append(f"measure {ms['name']}: expr must be a bare column - put arithmetic in the fact")

    names = set()
    labels: dict[str, str] = {}

    def unique_label(name: str, label: str | None) -> None:
        key = (label or name).strip().lower()
        if key in labels:
            errors.append(f"metric {name}: label {label!r} is already used by {labels[key]}")
        labels.setdefault(key, name)

    for m in sm["metrics"]:
        names.add(m["name"])
        meta = (m.get("config") or {}).get("meta") or {}
        where = f"metric {m['name']}"
        unique_label(m["name"], m.get("label"))
        for key in sorted(set(meta) - META_KEYS):
            errors.append(f"{where}: meta key {key!r} is not a governance key")
        if "requirement" in meta and not REQUIREMENT.fullmatch(str(meta["requirement"])):
            errors.append(f"{where}: requirement must be <dashboard code>-<slot>, e.g. O2C-M1")
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
        if b["name"] in names:
            errors.append(f"backlog {b['name']}: also defined in MetricFlow - a metric exists once")
        names.add(b["name"])
        unique_label(b["name"], b.get("label"))
        if b.get("status") not in BACKLOG_STATUSES:
            errors.append(f"backlog {b['name']}: status must be placeholder or blocked")
        reason = b.get("blocked_reason") if b.get("status") == "blocked" else b.get("placeholder_reason")
        if not reason:
            errors.append(f"backlog {b['name']}: a {b.get('status')} metric needs its reason")
        if not b.get("owner"):
            errors.append(f"backlog {b['name']}: owner is required (TBD is allowed)")

    for seed in ("process_metric.csv", "department_metric.csv"):
        with open(os.path.join(pack.seeds, seed)) as fh:
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
