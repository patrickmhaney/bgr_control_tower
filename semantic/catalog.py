"""The metric catalog: MetricFlow definitions + the backlog + the dashboard seeds.

    python -m semantic.catalog      # writes metric_catalog.json/.csv and the pack's docs/metric_catalog.md

One entry per metric with its definition, governance (status, owner,
caveats), the dimensions it can be cut by, whether a department dashboard can
show the department's own slice, which dashboards show it, which cubes store
it and how it rolls up there. Everything that needs to know about metrics
reads this: the data service, the docs, and any glossary that imports the CSV.
"""
from __future__ import annotations

import csv
import json
import os

import yaml

from core import project
from core.settings import settings


def _read_csv(name: str) -> list[dict]:
    with open(os.path.join(project.current().seeds, name)) as fh:
        return list(csv.DictReader(fh))


def _definition(m: dict) -> dict:
    tp = m.get("type_params") or {}
    d: dict = {"type": m["type"]}
    if m["type"] == "simple":
        measure = tp.get("measure") or {}
        d["measure"] = measure.get("name") if isinstance(measure, dict) else measure
    elif m["type"] == "ratio":
        d["numerator"] = (tp.get("numerator") or {}).get("name")
        d["denominator"] = (tp.get("denominator") or {}).get("name")
    elif m["type"] == "derived":
        d["expr"] = tp.get("expr")
        d["metrics"] = [x["name"] for x in tp.get("metrics") or []]
    elif m["type"] == "cumulative":
        measure = tp.get("measure") or {}
        d["measure"] = measure.get("name") if isinstance(measure, dict) else measure
        ctp = tp.get("cumulative_type_params") or {}
        window = ctp.get("window") or tp.get("window")
        if window:
            d["window"] = f"{window.get('count')} {window.get('granularity')}"
    flt = m.get("filter")
    if flt:
        d["filter"] = " and ".join(w["where_sql_template"] for w in flt.get("where_filters", []))
    return d


def _governance(m: dict) -> dict:
    """A metric's governance and labelling fields. The same keys whether `m`
    comes from the semantic manifest or straight from the YAML."""
    meta = (m.get("config") or {}).get("meta") or m.get("meta") or {}
    return {
        "label": m.get("label") or m["name"],
        "description": (m.get("description") or "").strip(),
        "role": meta.get("role", "kpi"), "status": meta.get("status"),
        "owner": meta.get("owner"), "owner_proposed": meta.get("owner_proposed"),
        "provisional_reason": (meta.get("provisional_reason") or "").strip() or None,
        "caveats": meta.get("caveats") or [],
        "format": meta.get("format"), "direction": meta.get("direction"),
        "is_data_quality": bool(meta.get("is_data_quality")),
    }


def _backlog_entry(b: dict) -> dict:
    return {
        "name": b["name"], "label": b["label"], "description": (b.get("description") or "").strip(),
        "source": "backlog", "type": None, "role": "kpi", "status": b["status"],
        "owner": b.get("owner"), "owner_proposed": b.get("owner_proposed"),
        "blocked_reason": (b.get("blocked_reason") or "").strip() or None,
        "placeholder_reason": (b.get("placeholder_reason") or "").strip() or None,
        "unblock_requires": b.get("unblock_requires") or [],
        "caveats": b.get("caveats") or [], "format": None, "direction": None,
        "is_data_quality": False, "definition": None, "base_models": [],
        "rollup": None, "cubes": [], "valid_dimensions": [],
    }


def _backlog() -> list[dict]:
    with open(project.current().backlog) as fh:
        return (yaml.safe_load(fh) or {}).get("metrics") or []


def _link(entries: list[dict]) -> list[dict]:
    """Where each metric is used, from the dashboard seeds."""
    process_map = _read_csv("process_metric.csv")
    dept_map = _read_csv("department_metric.csv")
    for e in entries:
        e["department_attributable"] = any(d.startswith("employee__department")
                                           for d in e["valid_dimensions"])
        e["processes"] = [{"process": r["process_code"], "slot": r["slot"]}
                          for r in process_map if r["metric_name"] == e["name"]]
        e["departments"] = [{"department": r["department_code"], "process": r["process_code"],
                             "influence": r["influence"]}
                            for r in dept_map if r["metric_name"] == e["name"]]
    return entries


def build_catalog(service=None) -> list[dict]:
    """Every metric, merged. `service` supplies valid dimensions from MetricFlow."""
    from semantic.rollup import load as load_rollups
    manifest, rollups = load_rollups(project.current().semantic_manifest)
    cubes = {sq["name"]: sq["query_params"]["metrics"] for sq in manifest.get("saved_queries", [])}
    measure_model = {ms["name"]: sm["node_relation"]["alias"]
                     for sm in manifest["semantic_models"] for ms in sm.get("measures", [])}

    out = []
    for m in manifest["metrics"]:
        entry = {"name": m["name"], **_governance(m), "source": "metricflow", "type": m["type"],
                 "definition": _definition(m), "rollup": rollups[m["name"]]["kind"],
                 "cubes": [c for c, ms in cubes.items() if m["name"] in ms]}
        inputs = [im["name"] for im in (m.get("type_params") or {}).get("input_measures", [])]
        entry["base_models"] = sorted({measure_model[i] for i in inputs if i in measure_model})
        entry["valid_dimensions"] = service.metric_dimensions(m["name"]) if service is not None else []
        out.append(entry)
    return _link(out + [_backlog_entry(b) for b in _backlog()])


def refresh(catalog: list[dict]) -> list[dict]:
    """A catalog built earlier, brought up to the files as they are now: the
    definitions and governance from the semantic YAML, the backlog, and the
    seeds. Formulas, cubes and dimensions stay as last compiled - they change
    only with a dbt parse. The Studio's Governance page reads this, so an edit
    shows at once, not after the next build."""
    from core import requirements

    pack = project.current()
    written = {}
    for path in requirements.semantic_files(pack)[:-1]:
        for m in requirements.load(path).get("metrics") or []:
            written[m["name"]] = m
    out = [{**e, **(_governance(written[e["name"]]) if e["name"] in written else {})}
           for e in catalog if e["source"] == "metricflow"]
    return _link(out + [_backlog_entry(b) for b in _backlog()])


def cube_index() -> list[dict]:
    """The saved queries: what each dashboard cube stores, at which grain."""
    from semantic.rollup import group_by_names
    from semantic.rollup import load as load_rollups
    manifest, _ = load_rollups(project.current().semantic_manifest)
    return [{"name": sq["name"], "grain": group_by_names(sq),
             "metrics": sq["query_params"]["metrics"],
             "description": (sq.get("description") or "").strip()}
            for sq in manifest.get("saved_queries", [])]


def write_outputs(catalog: list[dict]) -> None:
    os.makedirs(settings.exports_root if "://" not in settings.exports_root
                else settings.data_dir, exist_ok=True)
    out_dir = settings.exports_root if "://" not in settings.exports_root else settings.data_dir
    with open(os.path.join(out_dir, "metric_catalog.json"), "w") as fh:
        json.dump(catalog, fh, indent=2, default=str)
    with open(os.path.join(out_dir, "metric_catalog.csv"), "w", newline="") as fh:
        cols = ["name", "label", "status", "owner", "owner_proposed", "description", "format",
                "department_attributable", "source"]
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for e in catalog:
            if e["role"] == "kpi":
                w.writerow(e)
    with open(os.path.join(project.current().docs, "metric_catalog.md"), "w") as fh:
        fh.write(render_markdown(catalog))


def render_markdown(catalog: list[dict]) -> str:
    lines = [
        "# Metric catalogue",
        "",
        "Generated by `python -m semantic.catalog` from the MetricFlow definitions",
        "(the pack's `models/semantic/`), `backlog.yml` and the dashboard seeds.",
        "Do not edit by hand.",
        "",
        "| Metric | Status | Owner | Cut by department | Dashboards | Rolls up |",
        "|---|---|---|---|---|---|",
    ]
    kpis = [e for e in catalog if e["role"] == "kpi"]
    for e in kpis:
        dash = ", ".join(sorted({p["process"] for p in e["processes"]})) or "-"
        dept = "yes" if e["department_attributable"] else ("-" if e["source"] == "backlog" else "no")
        lines.append(f"| [{e['label']}](#{e['name']}) | {e['status']} | {e['owner']}"
                     f"{' (proposed: ' + e['owner_proposed'] + ')' if e.get('owner_proposed') else ''}"
                     f" | {dept} | {dash} | {e['rollup'] or '-'} |")
    for e in kpis:
        lines += ["", f"## {e['label']}", "", f"<a id=\"{e['name']}\"></a>`{e['name']}` · "
                  f"**{e['status']}** · owner {e['owner']}", "", e["description"], ""]
        if e["definition"]:
            d = e["definition"]
            parts = [f"type `{d['type']}`"] + [f"{k} `{v}`" for k, v in d.items() if k != "type"]
            lines.append("Definition: " + ", ".join(parts) + ".")
            lines.append("")
            lines.append(f"Base models: {', '.join(e['base_models']) or '-'}.")
            lines.append("")
            lines.append(f"In cubes: {', '.join(f'`{c}`' for c in e['cubes']) or '-'}; "
                         f"rolls up as `{e['rollup']}`.")
        for key in ("provisional_reason", "blocked_reason", "placeholder_reason"):
            if e.get(key):
                lines += ["", f"**{key.replace('_', ' ').capitalize()}.** {e[key]}"]
        for c in e["caveats"]:
            lines += ["", f"> Caveat: {c}"]
        if e["valid_dimensions"]:
            dims = [d for d in e["valid_dimensions"] if not d.startswith("metric_time")]
            lines += ["", "Can be cut by: " + ", ".join(f"`{d}`" for d in dims)
                      + ", and `metric_time` at day, week, month, quarter, year or fiscal grains."]
    lines += ["", "## Dashboard cubes", "",
              "Each saved query is one cube: its metrics at one grain, stacked into",
              "`marts.dashboard_cube` under its name in `_cube`. A `sum` or `ratio` metric",
              "rolls up from a cube to any coarser grain; a `fixed` one shows only at the",
              "cube's own grain.", "",
              "| Cube | Grain | Metrics |", "|---|---|---|"]
    for c in cube_index():
        lines.append(f"| `{c['name']}` | {', '.join(f'`{g}`' for g in c['grain'])} | "
                     f"{', '.join(c['metrics'])} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    from serving.semantic_service import SemanticService

    catalog = build_catalog(SemanticService())
    write_outputs(catalog)
    print(f"{len([e for e in catalog if e['role'] == 'kpi'])} KPIs, "
          f"{len(catalog)} metrics in the catalog")


if __name__ == "__main__":
    main()
