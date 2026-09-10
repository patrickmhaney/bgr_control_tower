"""Answer a metric question from the registry alone.

    python scripts/ask_metric.py --list
    python scripts/ask_metric.py on_time_delivery_rate --describe
    python scripts/ask_metric.py on_time_delivery_rate \
        --where site.city=Reno --period 2026-Q2
    python scripts/ask_metric.py on_time_delivery_rate --by carrier.carrier_name
    python scripts/ask_metric.py dso_days_to_pay_proxy

A secondary goal of the design is that an agent should be able to answer
"what was on-time delivery for the Reno site last quarter" without being
handed SQL or a data dictionary. This is the smallest thing that demonstrates
the semantic layer actually supports that: it reads only
exports/semantic/metric_registry.json (written by compile_metrics.py),
resolves the metric, its base model, its conformed dimensions and their
attributes, writes the SQL itself, and runs it.

There is no metric knowledge in this file. Point it at a registry with fifty
metrics and it answers fifty kinds of question.

Caveats travel with the number: a provisional metric is labelled as one, and
a blocked metric reports why the number does not exist instead of producing
one - an agent that cannot see the gap will confidently invent a number.
"""
import argparse
import json
import os
import sys

import duckdb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTRY = os.path.join(ROOT, "exports", "semantic", "metric_registry.json")
WAREHOUSE = os.path.join(ROOT, "warehouse.duckdb")

METRIC_SCHEMA = "main_metrics"
CORE_SCHEMA = "main_core"


def load():
    if not os.path.exists(REGISTRY):
        raise SystemExit(
            "No compiled registry. Run: python scripts/compile_metrics.py")
    return json.load(open(REGISTRY))


def find(registry, name):
    for metric in registry["metrics"]:
        if metric["name"] == name:
            return metric
    known = ", ".join(m["name"] for m in registry["metrics"])
    raise SystemExit(f"Unknown metric '{name}'. Known metrics: {known}")


def describe(registry, metric):
    print(f"{metric['label']}  ({metric['name']})")
    print(f"  status      {metric['status']}"
          + ("  [data quality metric]" if metric["is_data_quality"] else ""))
    print(f"  owner       {metric['owner']}"
          + (f"  (proposed: {metric['owner_proposed']})"
             if metric.get("owner_proposed") else ""))
    processes = ", ".join(f"{p['process_code']} {p['slot']}"
                          for p in metric["processes"]) or "not on any dashboard"
    print(f"  dashboards  {processes}")
    print(f"  grain       {metric['grain']}")
    print()
    print("  " + wrap(metric["description"], 4))
    if metric["status"] == "blocked":
        print()
        print("  BLOCKED")
        print("  " + wrap(metric["blocked_reason"], 4))
        if metric.get("unblock_requires"):
            print("\n  To unblock:")
            for requirement in metric["unblock_requires"]:
                print("    - " + wrap(requirement, 6).lstrip())
        return
    if metric.get("provisional_reason"):
        print()
        print("  PROVISIONAL")
        print("  " + wrap(metric["provisional_reason"], 4))
    if metric.get("companion_metric"):
        print(f"\n  Must be published with: {metric['companion_metric']}")
    print()
    print(f"  base model  {metric['base_model']}")
    print(f"  sliceable by {', '.join(metric['dimensions']) or 'nothing'}")
    print(f"  numerator   {agg_text(metric['numerator'])}")
    print(f"  denominator {agg_text(metric['denominator'])}")
    if not metric.get("is_reaggregatable", True):
        print("  NOTE: not re-aggregatable - do not sum this across dimension values.")
    for caveat in metric.get("caveats", []):
        print("\n  CAVEAT: " + wrap(caveat, 4).lstrip())
    if metric.get("lineage_notes"):
        print("\n  Lineage: " + wrap(metric["lineage_notes"], 4).lstrip())


def agg_text(spec):
    text = f"{spec['agg']}({spec['expression']})"
    if spec.get("filter"):
        text += f" where {spec['filter']}"
    return text


def wrap(text, indent, width=76):
    import textwrap
    return ("\n" + " " * indent).join(
        textwrap.wrap(" ".join(text.split()), width - indent))


def parse_period(period):
    """Accept 2026-Q2, 2026Q2, 2026-06 or 2026. Returns (clause, params)."""
    p = period.upper().replace("-", "")
    if "Q" in p:
        year, quarter = p.split("Q")
        return "date.calendar_year = ? and date.calendar_quarter = ?", [int(year), int(quarter)]
    if len(p) == 6:
        return "date.calendar_year = ? and date.calendar_month = ?", [int(p[:4]), int(p[4:])]
    if len(p) == 4:
        return "date.calendar_year = ?", [int(p)]
    raise SystemExit(f"Cannot parse period '{period}'. Use 2026-Q2, 2026-06 or 2026.")


def build_sql(registry, metric, wheres, group_by, period):
    """Build the query, and the parameters that go with it.

    Two things this has to get right:

    **C2 - re-aggregation.** A metric whose registry entry says
    `is_reaggregatable: false` cannot be totalled by summing the pre-aggregated
    numerator and denominator: `cost_per_order`'s denominator is a distinct
    count, and summing distinct counts double-counts anything spanning two
    dimension values. Those metrics are computed against the base fact with the
    declared aggregation applied directly. The registry already carries
    `numerator.agg`, `.column`, `.filter` and the model's dimension bindings, so
    no extra metadata is needed - only the FROM and the two aggregates change.

    **P5 - parameters.** Dimension and attribute names are validated against the
    registry, but filter *values* come from the caller. This script is the
    stated prototype for the agent-facing interface, and an agent passing user
    text into a value filter is exactly the shape that goes wrong, so values are
    bound rather than interpolated.
    """
    dimensions = registry["dimensions"]
    reaggregatable = metric.get("is_reaggregatable", True)

    joins, conditions, params, selects, groups = [], [], [], [], []
    needed = set()

    for clause in wheres:
        if "=" not in clause:
            raise SystemExit(f"--where expects dimension.attribute=value, got '{clause}'")
        left, value = clause.split("=", 1)
        dim, _, attribute = left.partition(".")
        needed.add(dim)
        validate_attribute(dimensions, metric, dim, attribute)
        conditions.append(f"{dim}.{attribute} = ?")
        params.append(value)

    for spec in group_by:
        dim, _, attribute = spec.partition(".")
        needed.add(dim)
        validate_attribute(dimensions, metric, dim, attribute)
        selects.append(f"{dim}.{attribute}")
        groups.append(f"{dim}.{attribute}")

    if period:
        needed.add("date")
        clause, period_params = parse_period(period)
        conditions.append(clause)
        params.extend(period_params)

    if reaggregatable:
        source = f"{METRIC_SCHEMA}.{metric['sql_model']}"
        numerator = "sum(m.numerator)"
        denominator = "sum(m.denominator)"
        key_of = lambda dim: dimensions[dim]["key"]  # noqa: E731
    else:
        # Straight off the fact, with the declared aggregation applied once.
        source = f"{CORE_SCHEMA}.{metric['base_model']}"
        model_bindings = registry["models"][metric["base_model"]]["dimension_columns"]
        numerator = agg_expression(metric["numerator"])
        denominator = agg_expression(metric["denominator"])
        for spec in metric.get("filters") or []:
            conditions.append(filter_sql(spec, params))
        key_of = lambda dim: model_bindings[dim]  # noqa: E731

    for dim in sorted(needed):
        d = dimensions[dim]
        joins.append(
            f"    join {CORE_SCHEMA}.{d['model']} as {dim} "
            f"on {dim}.{d['key']} = m.{key_of(dim)}")

    select_clause = "".join(f"    {s},\n" for s in selects)
    join_clause = ("\n".join(joins) + "\n") if joins else ""
    where_clause = ("where " + "\n  and ".join(conditions) + "\n") if conditions else ""
    group_clause = (f"group by {', '.join(str(i + 1) for i in range(len(groups)))}\n"
                    if groups else "")
    order_clause = "order by 1\n" if groups else ""

    sql = (
        "select\n"
        + select_clause
        + f"    {numerator} as numerator,\n"
        f"    {denominator} as denominator,\n"
        f"    {numerator} / nullif({denominator}, 0) as value\n"
        f"from {source} as m\n"
        + join_clause
        + where_clause
        + group_clause
        + order_clause
    ).rstrip()
    return sql, params


AGG_SQL = {
    "sum": "sum({c})",
    "count": "count({c})",
    "count_distinct": "count(distinct {c})",
    "avg": "avg({c})",
    "min": "min({c})",
    "max": "max({c})",
}

FILTER_SQL = {
    "is_true": "{c}",
    "is_false": "not {c}",
    "is_null": "{c} is null",
    "is_not_null": "{c} is not null",
    "eq": "{c} = ?",
    "ne": "{c} <> ?",
    "gt": "{c} > ?",
    "gte": "{c} >= ?",
    "lt": "{c} < ?",
    "lte": "{c} <= ?",
}


def filter_sql(spec, params):
    """Render one structured filter, binding any value into `params`."""
    column, op = spec["column"], spec["op"]
    if op == "in":
        placeholders = ", ".join("?" for _ in spec["value"])
        params.extend(spec["value"])
        return f"m.{column} in ({placeholders})"
    if op not in FILTER_SQL:
        raise SystemExit(f"filter op '{op}' is not supported by this client")
    if "?" in FILTER_SQL[op]:
        params.append(spec["value"])
    return "m." + FILTER_SQL[op].format(c=column)


def agg_expression(side):
    """The declared aggregation, applied to the base fact.

    Uses a CASE rather than a FILTER clause so the generated SQL stays portable
    - this is the one query in the project a consumer might run somewhere other
    than DuckDB.
    """
    column = f"m.{side['column']}"
    if side.get("filter"):
        guard_params: list = []
        condition = filter_sql(side["filter"], guard_params)
        if guard_params:
            raise SystemExit(
                "measure-level filters with values are not supported by this "
                "client for non-re-aggregatable metrics; add support in "
                "agg_expression() if a metric needs one."
            )
        column = f"case when {condition} then {column} end"
    return AGG_SQL[side["agg"]].format(c=column)


def validate_attribute(dimensions, metric, dim, attribute):
    if dim not in dimensions:
        raise SystemExit(
            f"'{dim}' is not a conformed dimension. Available: "
            f"{', '.join(dimensions)}")
    if dim not in metric["dimensions"]:
        raise SystemExit(
            f"{metric['label']} cannot be sliced by '{dim}'. It supports: "
            f"{', '.join(metric['dimensions']) or 'nothing'}")
    if attribute not in dimensions[dim]["attributes"]:
        raise SystemExit(
            f"'{attribute}' is not an attribute of dimension '{dim}'. Available: "
            f"{', '.join(dimensions[dim]['attributes'])}")


def format_value(value, fmt):
    if value is None:
        return "-"
    value = float(value)
    if fmt == "percent":
        return f"{value * 100:.1f}%"
    if fmt == "currency_usd":
        return f"${value:,.2f}"
    if fmt == "days":
        return f"{value:.1f} days"
    return f"{value:,.2f}"


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("metric", nargs="?", help="metric name")
    parser.add_argument("--list", action="store_true", help="list every registered metric")
    parser.add_argument("--describe", action="store_true", help="explain the metric and stop")
    parser.add_argument("--where", action="append", default=[],
                        metavar="DIM.ATTR=VALUE", help="filter, repeatable")
    parser.add_argument("--by", action="append", default=[],
                        metavar="DIM.ATTR", help="group by, repeatable")
    parser.add_argument("--period", help="2026-Q2, 2026-06 or 2026")
    parser.add_argument("--sql", action="store_true", help="print the generated SQL")
    args = parser.parse_args()

    registry = load()

    if args.list or not args.metric:
        print(f"{'metric':34} {'status':12} {'dashboards':16} owner")
        print("-" * 84)
        for metric in registry["metrics"]:
            processes = ",".join(p["process_code"] for p in metric["processes"]) or "-"
            print(f"{metric['name']:34} {metric['status']:12} {processes:16} {metric['owner']}")
        return 0

    metric = find(registry, args.metric)

    if args.describe:
        describe(registry, metric)
        return 0

    if not metric["queryable"]:
        print(f"{metric['label']} cannot be computed.")
        print()
        print(wrap(metric["blocked_reason"], 0))
        print()
        if metric.get("unblock_requires"):
            print("To unblock, the business needs to supply:")
            for requirement in metric["unblock_requires"]:
                print("  - " + wrap(requirement, 4).lstrip())
        print()
        print("No number is returned, deliberately. A blocked metric with a "
              "plausible\nnumber beside it is worse than an empty one.")
        return 0

    sql, params = build_sql(registry, metric, args.where, args.by, args.period)
    if args.sql:
        print(sql + "\n")
        if params:
            print(f"-- parameters: {params}\n")

    con = duckdb.connect(WAREHOUSE, read_only=True)
    try:
        cursor = con.execute(sql, params)
        columns = [d[0] for d in cursor.description]
        rows = cursor.fetchall()
    finally:
        con.close()

    print(f"{metric['label']} ({metric['status']})")
    if metric.get("provisional_reason"):
        print("  PROVISIONAL: " + wrap(metric["provisional_reason"], 2).lstrip())
    if metric.get("companion_metric"):
        print(f"  Publish alongside: {metric['companion_metric']}")
    if not metric.get("is_reaggregatable", True):
        print("  Not re-aggregatable, so this is computed from "
              f"{metric['base_model']} directly rather than from the "
              "pre-aggregated metric model.")
    print()

    label_columns = columns[:-3]
    if not rows or all(r[-2] in (None, 0) for r in rows):
        print("  no rows matched")
        return 0
    for row in rows:
        labels = "  ".join(str(v) for v in row[:len(label_columns)])
        numerator, denominator, value = row[-3:]
        prefix = f"  {labels:34}" if label_columns else "  "
        count = "n/a" if denominator is None else f"{denominator:,.0f}"
        print(f"{prefix}{format_value(value, metric['format']):>12}"
              f"    (n = {count})")

    for caveat in metric.get("caveats", []):
        print("\n  CAVEAT: " + wrap(caveat, 4).lstrip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
