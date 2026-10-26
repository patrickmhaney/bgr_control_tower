"""The Governance screen: every metric with its definition, ownership, lifecycle and proof.

Nothing here is written down twice. The catalog is semantic.catalog's (the
one the data service, the MCP tools and the pack's docs/metric_catalog.md read); the
measures and their tables come from the compiled manifests; the proof is the
governance lint run live and the golden answers that name each metric; usage
is the data service's audit log.
"""
from __future__ import annotations

import csv
import json
import os
import re
from collections import Counter

import yaml

from core import project
from core.settings import ROOT, settings


def _seed(name: str) -> list[dict]:
    with open(os.path.join(project.current().seeds, name)) as fh:
        return list(csv.DictReader(fh))


def _measures() -> tuple[dict, dict]:
    """{measure: {agg, column, model, table, owner}}, and {metric: [measure, ...]}."""
    with open(project.current().semantic_manifest) as fh:
        sm = json.load(fh)
    with open(project.current().manifest) as fh:
        nodes = json.load(fh)["nodes"].values()
    owners = {n["name"]: (n["config"].get("meta") or {}).get("owner")
              for n in nodes if n["resource_type"] == "model"}
    measures = {}
    for model in sm["semantic_models"]:
        table = model["node_relation"]["alias"]
        for ms in model.get("measures", []):
            measures[ms["name"]] = {"name": ms["name"], "agg": ms["agg"].lower(), "column": ms.get("expr") or ms["name"],
                                    "model": model["name"], "table": table, "owner": owners.get(table)}
    uses = {m["name"]: [i["name"] for i in (m.get("type_params") or {}).get("input_measures", [])]
            for m in sm["metrics"]}
    return measures, uses


def _golden() -> dict[str, list[dict]]:
    with open(project.current().golden) as fh:
        queries = yaml.safe_load(fh)["queries"]
    out: dict[str, list[dict]] = {}
    for q in queries:
        for m in q.get("metrics") or []:
            out.setdefault(m, []).append({"id": q["id"], "refusal": q.get("expect_refusal"),
                                          "group_by": q.get("group_by") or []})
    return out


def _usage() -> dict[str, dict]:
    """Requests per metric through the data API and the MCP tools, from the audit log."""
    path = os.path.join(settings.data_dir, "audit", "queries.jsonl")
    out: dict[str, dict] = {}
    if not os.path.exists(path):
        return out
    with open(path) as fh:
        for line in fh:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            for m in e.get("metrics") or []:
                u = out.setdefault(m, {"requests": 0, "routes": Counter(), "last": None})
                u["requests"] += 1
                u["routes"][e.get("route", "?")] += 1
                u["last"] = max(u["last"] or "", e.get("at", ""))
    return {m: {**u, "routes": dict(u["routes"])} for m, u in out.items()}


def _source(name: str, source: str) -> dict | None:
    """The metric's own lines in the file that defines it, exactly as written."""
    pack = project.current()
    full = {"metricflow": os.path.join(pack.semantic_dir, "metrics.yml"), "backlog": pack.backlog}.get(source)
    if not full:
        return None
    path = os.path.relpath(full, ROOT)
    with open(os.path.join(ROOT, path)) as fh:
        lines = fh.read().splitlines()
    start = next((i for i, line in enumerate(lines)
                  if re.match(rf"^(\s*)- \{{?name: {re.escape(name)}\b", line)), None)
    if start is None:
        return None
    indent = len(lines[start]) - len(lines[start].lstrip())
    end = start + 1
    while end < len(lines) and (not lines[end].strip() or len(lines[end]) - len(lines[end].lstrip()) > indent):
        end += 1
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1
    return {"path": path, "line": start + 1, "text": "\n".join(lines[start:end])}


def _rules() -> list[str]:
    """The governance lint's rules, as its own docstring states them."""
    import semantic.lint

    text = re.sub(r"\n\s+(?!\*)", " ", semantic.lint.__doc__ or "")
    return [r.strip() for r in re.findall(r"^\* (.+)$", text, re.M)]


def snapshot(service) -> dict:
    from semantic.lint import lint
    from serving.powerbi import Cube, measure_dax

    from . import data

    catalog = list(service.catalog.values())
    measures, uses = _measures()
    golden, usage = _golden(), _usage()
    cube = Cube()
    departments = {d["department_code"]: d["department_name"] for d in _seed("department.csv")}
    titles = {name: data._title(name) for name in cube.cubes}
    processes = {m.group(1).upper(): data._title(name) for name in cube.cubes
                 if (m := data.PROCESS.match(name))}
    metrics = []
    for e in catalog:
        entry = {k: e.get(k) for k in (
            "name", "label", "description", "source", "type", "role", "status", "owner", "owner_proposed",
            "provisional_reason", "blocked_reason", "placeholder_reason", "unblock_requires", "caveats",
            "format", "direction", "is_data_quality", "definition", "rollup", "cubes", "base_models",
            "department_attributable", "processes")}
        entry["departments"] = [{**d, "name": departments.get(d["department"], d["department"])}
                                for d in e.get("departments") or []]
        entry["measures"] = [measures[m] for m in uses.get(e["name"], []) if m in measures]
        entry["pages"] = [titles[c] for c in e.get("cubes") or [] if c in titles]
        entry["golden"] = golden.get(e["name"], [])
        entry["usage"] = usage.get(e["name"])
        entry["yaml"] = _source(e["name"], e["source"])
        dims = [d for d in e.get("valid_dimensions") or [] if not d.startswith("metric_time")]
        entry["dimensions"] = {"count": len(dims),
                               "entities": sorted(Counter(d.split("__")[0] for d in dims).items())}
        if e["name"] in cube.kpis:
            entry["dax"] = measure_dax(e["name"], cube.rollups[e["name"]])
        for ref in ("numerator", "denominator"):
            name = (e.get("definition") or {}).get(ref)
            if name:
                entry[f"{ref}_label"] = cube.label(name) if name in cube.metrics else name
        metrics.append(entry)

    errors = lint()
    return {"metrics": metrics, "lint": {"rules": _rules(), "errors": errors},
            "golden_total": len({q["id"] for qs in golden.values() for q in qs}),
            "processes": processes, "departments": departments,
            "measures": sorted(measures.values(), key=lambda m: (m["table"], m["name"])),
            "measure_uses": {ms: sorted(m for m, ins in uses.items() if ms in ins) for ms in measures}}
