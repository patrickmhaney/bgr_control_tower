"""The Studio's preview consumers: dashboards over the cube, SQL over gold and the marts.

Dashboards read marts.dashboard_cube through the Power BI measure templates'
SQL (serving.powerbi.measure_sql), one saved query per page, so every number
is the one the Power BI model would show and no metric logic lives here.

All reads are short-lived read-only connections, one at a time, and only when
nothing is writing: a reader holding the file would make the pipeline fail.
"""
from __future__ import annotations

import datetime as dt
import decimal
import re
import threading
import time
from functools import lru_cache

import duckdb
import yaml

from core import lock
from core.settings import settings

WAREHOUSE = threading.Lock()
ROW_LIMIT = 1000
TIMEOUT_S = 15
FORMATS = {"percent": "percent", "currency_usd": "usd", "days": "days", "count": "int"}
TITLES = {"mart_company_monthly": "Company", "mart_department_scorecard": "Departments",
          "mart_customer_scorecard": "Customers", "mart_platform_cost": "Platform cost"}


class Busy(RuntimeError):
    pass


def busy_reason(running: bool) -> str | None:
    if running:
        return "A pipeline step is writing the warehouse. Try again when it finishes."
    held = lock.holder()
    if held:
        return f"The pipeline is running ({held['command']}). Try again when it finishes."
    return None


def _cell(v):
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()[:10] if isinstance(v, dt.date) and not isinstance(v, dt.datetime) else v.isoformat()
    return v


def _read(sql: str, params=None, config: dict | None = None):
    with WAREHOUSE:
        con = duckdb.connect(settings.warehouse_path, read_only=True, config=config or {})
        timer = threading.Timer(TIMEOUT_S, con.interrupt)
        timer.start()
        try:
            cur = con.execute(sql, params or [])
            cols = [d[0] for d in cur.description]
            rows = cur.fetchmany(ROW_LIMIT + 1)
            return cols, [[_cell(v) for v in r] for r in rows]
        finally:
            timer.cancel()
            con.close()


@lru_cache(maxsize=1)
def _cube():
    from serving.powerbi import Cube

    return Cube()


def _title(name: str) -> str:
    if name in TITLES:
        return TITLES[name]
    short = name.removeprefix("mart_").replace("_", " ")
    return short.upper() if len(short) <= 3 else short.capitalize()


# ------------------------------------------------------------- dashboards --
def pages() -> list[dict]:
    cube = _cube()
    out = []
    for name, c in cube.cubes.items():
        out.append({"id": name, "title": _title(name), "description": c["description"],
                    "dims": [{"id": d, "label": cube.names[d]} for d in c["dims"]],
                    "metrics": [{"id": m, "label": cube.label(m), "kind": cube.rollups[m]["kind"],
                                 "fmt": FORMATS.get(cube.meta(m).get("format"), "int"),
                                 "better": {"higher_is_better": "up", "lower_is_better": "down"}.get(
                                     cube.meta(m).get("direction")),
                                 "status": cube.meta(m).get("status")}
                                for m in c["metrics"]]})
    return out


def _months(today: dt.date, n: int) -> list[dt.date]:
    first = today.replace(day=1)
    out = []
    for _ in range(n):
        out.append(first)
        first = (first - dt.timedelta(days=1)).replace(day=1)
    return out[::-1]


def page(name: str, metric: str | None, period: str, today: dt.date, dim: str | None = None) -> dict:
    """Cards, a trend and a breakdown for one saved query - the visuals a Power BI page would hold."""
    from serving.powerbi import measure_sql

    cube = _cube()
    c = cube.cubes[name]
    metric = metric if metric in c["metrics"] else c["metrics"][0]
    months = _months(today, 12)
    start = {"month": today.replace(day=1), "ytd": today.replace(month=1, day=1), "12m": months[0]}[period]
    others = [d for d in c["dims"] if d != "metric_time__month"]
    by_month_ok = c["dims"] == ["metric_time__month"]

    def expr(m):
        return measure_sql(m, cube.rollups[m])

    def additive(m):
        return cube.rollups[m]["kind"] != "fixed"

    where = "_cube = ? and metric_time__month >= ?"
    # Cards: each metric over the period, and a monthly sparkline. A fixed
    # metric only exists at the cube's own grain, so it is blank above it -
    # exactly as the Power BI measure is.
    rollable = [m for m in c["metrics"] if additive(m)]
    totals = {}
    if rollable:
        _, rows = _read(f"select {', '.join(expr(m) for m in rollable)} from marts.dashboard_cube where {where}",
                        [name, start])
        totals = dict(zip(rollable, rows[0]))
    spark_metrics = [m for m in c["metrics"] if additive(m) or by_month_ok]
    series = {}
    if spark_metrics:
        cols, rows = _read(f"select metric_time__month, {', '.join(expr(m) for m in spark_metrics)} "
                           f"from marts.dashboard_cube where {where} group by 1 order by 1",
                           [name, months[0]])
        for r in rows:
            for m, v in zip(spark_metrics, r[1:]):
                series.setdefault(m, {})[r[0]] = v
    month_keys = [m.isoformat() for m in months]

    def latest(m) -> dt.date:
        """The most recent month a fixed metric has a value for (forecasts lag a month)."""
        _, rows = _read(f'select max(metric_time__month) from marts.dashboard_cube '
                        f'where _cube = ? and "{m}" is not null', [name])
        return dt.date.fromisoformat(rows[0][0]) if rows[0][0] else today.replace(day=1)

    cards = []
    for m in c["metrics"]:
        value = totals.get(m)
        note = None
        if not additive(m):
            if by_month_ok:
                last = latest(m)
                value = series.get(m, {}).get(last.isoformat())
                note = f"{last:%B %Y} only: this metric does not add up across months"
            else:
                note = "Shown at the page's full grain only, in the table below"
        # Sparklines show complete months; the current one has only a few days in it.
        cards.append({"metric": m, "value": value, "note": note,
                      "spark": [series.get(m, {}).get(k) for k in month_keys[:-1]] if m in series else None})

    current = today.replace(day=1).isoformat()
    trend = [{"month": k, "value": series.get(metric, {}).get(k), "partial": k == current} for k in month_keys]

    breakdown, table = None, None
    dim = dim if dim in others else (others[0] if others else None)
    if additive(metric) and others:
        _, rows = _read(f'select "{dim}", {expr(metric)} as v from marts.dashboard_cube where {where} '
                        f'group by 1 having v is not null order by v desc nulls last limit 15', [name, start])
        breakdown = {"dim": dim, "label": cube.names[dim], "rows": [{"label": r[0], "value": r[1]} for r in rows]}
    elif not additive(metric) and others:
        dims = ", ".join(f'"{d}"' for d in others)
        last = latest(metric)
        cols, rows = _read(f'select {dims}, {expr(metric)} as v from marts.dashboard_cube '
                           f'where _cube = ? and metric_time__month = ? group by {dims} order by {dims} limit 60',
                           [name, last])
        table = {"columns": [cube.names[d] for d in others] + [cube.label(metric)], "rows": rows,
                 "month": f"{last:%B %Y}"}
    return {"page": name, "metric": metric, "period": period, "start": start.isoformat(),
            "cards": cards, "trend": trend, "breakdown": breakdown, "table": table,
            "trend_note": None if trend and any(t["value"] is not None for t in trend) else
            "This metric does not add up across the page's other dimensions, so it has no company-wide trend here."}


# ------------------------------------------------------------------ query --
ALLOWED = re.compile(r"^\s*(select|with|from|describe|summarize|show|pivot|unpivot|explain|values)\b", re.I)


def schema() -> list[dict]:
    _, rows = _read("select schema_name, table_name, column_name, data_type from duckdb_columns() "
                    "where schema_name in ('gold', 'marts') order by schema_name, table_name, column_index")
    out: dict[tuple, dict] = {}
    for s, t, col, typ in rows:
        out.setdefault((s, t), {"schema": s, "table": t, "columns": []})["columns"].append(
            {"name": col, "type": typ})
    return list(out.values())


def examples() -> list[dict]:
    from evaluation.golden import GOLDEN

    with open(GOLDEN) as fh:
        queries = yaml.safe_load(fh)["queries"]
    out = [{"label": "Every table in the Power BI cube, by saved query",
            "sql": "select _cube, count(*) as rows\nfrom marts.dashboard_cube\ngroup by 1\norder by 1"}]
    for q in queries:
        if q.get("reference_sql"):
            out.append({"label": q["id"].replace("_", " "), "sql": q["reference_sql"].strip()})
    return out


def run_sql(sql: str) -> dict:
    """A read-only query with a row limit and a time limit. No file access."""
    sql = sql.strip().rstrip(";").strip()
    if not sql:
        raise ValueError("Write a query first.")
    if ";" in sql:
        raise ValueError("One statement at a time.")
    if not ALLOWED.match(sql):
        raise ValueError("Only read queries (SELECT, WITH, DESCRIBE, SUMMARIZE ...) can run here.")
    started = time.perf_counter()
    try:
        cols, rows = _read(sql, config={"enable_external_access": False})
    except duckdb.InterruptException:
        raise ValueError(f"The query took longer than {TIMEOUT_S} seconds and was stopped.") from None
    except duckdb.Error as exc:
        raise ValueError(str(exc).strip().splitlines()[0]) from None
    return {"columns": cols, "rows": rows[:ROW_LIMIT], "truncated": len(rows) > ROW_LIMIT,
            "ms": round((time.perf_counter() - started) * 1000)}
