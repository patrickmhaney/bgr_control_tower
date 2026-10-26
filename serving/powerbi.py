"""Generate the Power BI semantic model (TMDL): one table, three measure templates.

    python -m serving.powerbi           # writes powerbi/ControlTower.SemanticModel/definition/

Power BI computes nothing of its own. It imports one table, marts.dashboard_cube
(serving/materialize.py), in which MetricFlow has already computed every
number at the grains the saved queries name. Each KPI becomes one measure,
and every measure is one of three templates, picked by how the metric rolls
up (semantic/rollup.py):

    sum     IF(HASONEVALUE(Cube), SUM(metric))
    ratio   IF(HASONEVALUE(Cube), DIVIDE(SUM(numerator), SUM(denominator)))
    fixed   IF(COUNTROWS(dashboard_cube) = 1, MAX(metric))

The guards make a wrong number impossible to show. Rows from two cubes never
add up (a visual must be filtered to one `Cube`), and a fixed metric shows
only where the visual lands on exactly one stored row - anywhere else it is
blank, never an average of averages. Sums and ratios roll up correctly to any
grain coarser than their cube, including totals.

Rule 6 in PLAN.md §9.3: the table loads through one M function, LoadMart, in
expressions.tmdl. Pointing Power BI at Postgres, Fabric or Snowflake instead of
the Parquet export changes that one function.
"""
from __future__ import annotations

import json
import os
import re
import shutil

from core import project
from semantic.rollup import cube_columns, group_by_names
from semantic.rollup import load as load_rollups

TABLE = "dashboard_cube"

FORMATS = {"percent": "0.0%", "currency_usd": "\\$#,0", "days": "#,0.0", "count": "#,0"}
TMDL_TYPES = {"varchar": "string", "integer": "int64", "bigint": "int64", "double": "double",
              "date": "dateTime", "boolean": "boolean", "decimal": "decimal"}

#: The three measure templates, and the same arithmetic in SQL so the parity
#: check can prove them against the golden answers without Power BI.
DAX = {
    "sum": "IF(HASONEVALUE('{t}'[Cube]), SUM('{t}'[{m}]))",
    "ratio": "IF(HASONEVALUE('{t}'[Cube]), DIVIDE(SUM('{t}'[{n}]), SUM('{t}'[{d}])))",
    "fixed": "IF(COUNTROWS('{t}') = 1, MAX('{t}'[{m}]))",
}
SQL = {
    "sum": 'sum("{m}")',
    "ratio": 'sum("{n}") / nullif(sum("{d}"), 0)',
    "fixed": 'case when count(*) = 1 then max("{m}") end',
}


def _fill(template: str, metric: str, rollup: dict) -> str:
    return template.format(t=TABLE, m=metric, n=rollup.get("numerator"),
                           d=rollup.get("denominator"))


def measure_dax(metric: str, rollup: dict) -> str:
    return _fill(DAX[rollup["kind"]], metric, rollup)


def measure_sql(metric: str, rollup: dict) -> str:
    return _fill(SQL[rollup["kind"]], metric, rollup)


class Cube:
    """What dashboard_cube holds, read from the manifests: no warehouse needed."""

    def __init__(self):
        pack = project.current()
        self.sm, self.rollups = load_rollups(pack.semantic_manifest)
        with open(pack.manifest) as fh:
            nodes = json.load(fh)["nodes"].values()
        self.gold = {n["name"]: n for n in nodes
                     if n["resource_type"] == "model" and n["config"].get("schema") == "gold"}
        self.metrics = {m["name"]: m for m in self.sm["metrics"]}
        self.cubes = {sq["name"]: {"dims": group_by_names(sq),
                                   "metrics": sq["query_params"]["metrics"],
                                   "columns": cube_columns(sq, self.rollups),
                                   "description": (sq.get("description") or "").strip()}
                      for sq in self.sm.get("saved_queries", [])}
        self.dims = list(dict.fromkeys(d for c in self.cubes.values() for d in c["dims"]))
        self.columns = list(dict.fromkeys(m for c in self.cubes.values() for m in c["columns"]))
        self.kpis = [m for m in self.columns if self.meta(m).get("role") == "kpi"]
        self.names = _display_names(self.dims)

    def meta(self, metric: str) -> dict:
        m = self.metrics[metric]
        return (m.get("config") or {}).get("meta") or m.get("meta") or {}

    def label(self, metric: str) -> str:
        return self.metrics[metric].get("label") or metric

    def dim_type(self, dim: str) -> str:
        if dim.startswith("metric_time__"):
            return "dateTime"
        entity, name = dim.split("__", 1)
        for sm in self.sm["semantic_models"]:
            if not any(e["name"] == entity and e["type"] == "primary" for e in sm.get("entities", [])):
                continue
            for d in sm.get("dimensions", []):
                if d["name"] == name:
                    col = d.get("expr") or d["name"]
                    spec = self.gold.get(sm["node_relation"]["alias"], {}).get("columns", {}).get(col, {})
                    base = (spec.get("data_type") or "varchar").lower().split("(")[0].strip()
                    return TMDL_TYPES.get(base, "string")
        return "string"


def _display_names(dims: list[str]) -> dict[str, str]:
    """site__site_name -> Site Name; metric_time__month -> Month. Entity prefix on a clash."""
    short = {d: d.split("__", 1)[1] for d in dims}
    names = {}
    for d in dims:
        clash = sum(1 for v in short.values() if v == short[d]) > 1
        names[d] = (d if clash else short[d]).replace("__", " ").replace("_", " ").title()
    return {"_cube": "Cube", **names}


def _q(name: str) -> str:
    return name if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) else f"'{name}'"


def _doc(text: str, indent: str) -> list[str]:
    return [f"{indent}/// {line}" for line in text.splitlines() if line.strip()]


def _write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="\n") as fh:
        fh.write(text)


def generate_model() -> str:
    cube = Cube()
    out = project.current().powerbi_model
    if os.path.isdir(out):
        shutil.rmtree(out)
    _write(os.path.join(out, "database.tmdl"), "database\n\tcompatibilityLevel: 1600\n")
    _write(os.path.join(out, "model.tmdl"),
           "model Model\n\tculture: en-US\n\tdefaultPowerBIDataSourceVersion: powerBI_V3\n"
           "\tdiscourageImplicitMeasures\n\tsourceQueryCulture: en-US\n\n"
           f"ref table {TABLE}\n")
    _write(os.path.join(out, "expressions.tmdl"), EXPRESSIONS)

    lines = [f"table {TABLE}", ""]
    for m in cube.kpis:
        r = cube.rollups[m]
        meta = cube.meta(m)
        lines += _doc(f"{(cube.metrics[m].get('description') or '').strip()} "
                      f"Rolls up as: {r['kind']}.", "\t")
        lines.append(f"\tmeasure {_q(cube.label(m))} = {measure_dax(m, r)}")
        if meta.get("format") in FORMATS:
            lines.append(f"\t\tformatString: {FORMATS[meta['format']]}")
        lines += ["\t\tdisplayFolder: KPIs", ""]

    grains = "; ".join(f"{n} = {', '.join(cube.names[d] for d in c['dims']) or 'total'}"
                       for n, c in cube.cubes.items())
    lines += _doc("The saved query a row comes from. Filter every page or visual to one. "
                  f"Grains: {grains}.", "\t")
    lines += ["\tcolumn Cube", "\t\tdataType: string", "\t\tsummarizeBy: none",
              "\t\tsourceColumn: _cube", ""]
    for d in cube.dims:
        dtype = cube.dim_type(d)
        lines += [f"\tcolumn {_q(cube.names[d])}", f"\t\tdataType: {dtype}"]
        if d.endswith("__month"):
            lines.append("\t\tformatString: mmm yyyy")
        lines += ["\t\tsummarizeBy: none", f"\t\tsourceColumn: {d}", ""]
    # Stored values and ratio components: what the measures read, hidden from authors.
    for m in cube.columns:
        lines += [f"\tcolumn {m}", "\t\tdataType: double", "\t\tisHidden", "\t\tsummarizeBy: none",
                  f"\t\tsourceColumn: {m}", ""]
    lines += [f"\tpartition {TABLE} = m", "\t\tmode: import",
              f"\t\tsource = LoadMart(\"{TABLE}\")", ""]
    _write(os.path.join(out, "tables", f"{TABLE}.tmdl"), "\n".join(lines))
    print(f"powerbi model: 1 table, {len(cube.kpis)} measures, {len(cube.cubes)} cubes -> {out}")
    return out


EXPRESSIONS = """expression MartFolder = "C:\\\\control-tower\\\\exports\\\\marts\\\\" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]

expression MartSource = "local" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]

/// The only place the model knows where data lives (rule 6). "local" reads the
/// Parquet export from a folder; "adls" reads it from the storage account's
/// exports container (set MartFolder to its https://...dfs.core.windows.net/ URL).
/// Pointing the model at Postgres, Fabric or Snowflake replaces this function.
expression LoadMart =
		(name as text) as table =>
		let
			Bytes = if MartSource = "adls"
				then AzureStorage.DataLakeContents(MartFolder & name & ".parquet")
				else File.Contents(MartFolder & name & ".parquet"),
			Data = Parquet.Document(Binary.Buffer(Bytes))
		in
			Data
"""


if __name__ == "__main__":
    generate_model()
