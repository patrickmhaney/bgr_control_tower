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


def _read(sql: str, params=None, config: dict | None = None, limit: int = ROW_LIMIT):
    with WAREHOUSE:
        con = duckdb.connect(settings.warehouse_path, read_only=True, config=config or {})
        timer = threading.Timer(TIMEOUT_S, con.interrupt)
        timer.start()
        try:
            cur = con.execute(sql, params or [])
            cols = [d[0] for d in cur.description]
            rows = cur.fetchmany(limit + 1)
            return cols, [[_cell(v) for v in r] for r in rows]
        finally:
            timer.cancel()
            con.close()


@lru_cache(maxsize=1)
def _cube():
    from serving.powerbi import Cube

    return Cube()


# ------------------------------------------------------------- dashboards --
MONTH = "metric_time__month"
DASH_LIMIT = 5000
PERIODS = ("month", "qtd", "ytd", "12m")
#: Process names as the requirements plan spells them; the two sales and
#: revenue cubes are named for what they hold.
TITLES = {"mart_company_monthly": "Company scorecard", "mart_o2c": "Order to Cash", "mart_i2d": "Inventory to Delivery",
          "mart_s2p": "Source to Pay", "mart_f2p": "Forecast to Plan", "mart_p2c": "Sales pipeline",
          "mart_r2p": "Revenue", "mart_department_scorecard": "Departments",
          "mart_customer_scorecard": "Customers", "mart_platform_cost": "Platform cost"}
PROCESS = re.compile(r"^mart_([a-z]2[a-z])$")


def _title(name: str) -> str:
    if name in TITLES:
        return TITLES[name]
    short = name.removeprefix("mart_").replace("_", " ")
    return short.upper() if len(short) <= 3 else short.capitalize()


def _section(name: str) -> str:
    if PROCESS.match(name):
        return "Processes"
    if name.endswith("_scorecard"):
        return "Scorecards"
    return "Overview" if name == "mart_company_monthly" else "Platform"


def _dim_label(dim: str) -> str:
    return re.sub(r" (Name|Code)$", "", _cube().names[dim])


def _expr(m: str) -> str:
    from serving.powerbi import measure_sql

    return measure_sql(m, _cube().rollups[m])


def _kind(m: str) -> str:
    return _cube().rollups[m]["kind"]


def _weight(m: str) -> str | None:
    """What ranks the rows of a breakdown: the volume behind the number, not the number."""
    r = _cube().rollups[m]
    return _expr(r["denominator"]) if r["kind"] == "ratio" else _expr(m) if r["kind"] == "sum" else None


def _metric(m: str) -> dict:
    from serving.powerbi import measure_dax

    cube = _cube()
    meta, r = cube.meta(m), cube.rollups[m]
    out = {"id": m, "label": cube.label(m), "kind": r["kind"], "fmt": FORMATS.get(meta.get("format"), "int"),
           "better": {"higher_is_better": "up", "lower_is_better": "down"}.get(meta.get("direction")),
           "status": meta.get("status"), "description": (cube.metrics[m].get("description") or "").strip(),
           "owner": meta.get("owner"), "owner_proposed": meta.get("owner_proposed"),
           "provisional_reason": (meta.get("provisional_reason") or "").strip() or None,
           "caveats": meta.get("caveats") or [], "dax": measure_dax(m, r), "sql": _expr(m)}
    if r["kind"] == "ratio":
        out["numerator"], out["denominator"] = cube.label(r["numerator"]), cube.label(r["denominator"])
        out["denominator_fmt"] = FORMATS.get(cube.meta(r["denominator"]).get("format"), "int")
    return out


def _group(m: str) -> str:
    """The process a company-wide metric belongs to: the first process cube that holds it."""
    for name, c in _cube().cubes.items():
        if PROCESS.match(name) and m in c["metrics"]:
            return _title(name)
    return "Data quality" if _cube().meta(m).get("is_data_quality") else "Other"


def pages() -> list[dict]:
    cube = _cube()
    out = []
    for name, c in cube.cubes.items():
        code = PROCESS.match(name)
        out.append({"id": name, "title": _title(name), "code": code.group(1).upper() if code else None,
                    "section": _section(name), "description": c["description"],
                    "dims": [{"id": d, "label": _dim_label(d)} for d in c["dims"]],
                    "metrics": [_metric(m) for m in c["metrics"]],
                    "groups": [_group(m) for m in c["metrics"]] if len(c["metrics"]) > 6 else None})
    return out


def _shift(month: dt.date, n: int) -> dt.date:
    y, m = divmod(month.year * 12 + month.month - 1 + n, 12)
    return dt.date(y, m + 1, 1)


def _span(a: dt.date, b: dt.date) -> str:
    return f"{a:%b %Y}" if a == b else f"{a:%b}–{b:%b %Y}" if a.year == b.year else f"{a:%b %Y}–{b:%b %Y}"


def _windows(period: str, asof: dt.date) -> dict:
    """The selected months and the ones they are compared with: {key: (start, end, label)}."""
    start = {"month": asof, "qtd": asof.replace(month=(asof.month - 1) // 3 * 3 + 1),
             "ytd": asof.replace(month=1), "12m": _shift(asof, -11)}[period]
    py = (_shift(start, -12), _shift(asof, -12))
    out = {"cur": (start, asof, _span(start, asof))}
    if period == "month":
        prev = _shift(asof, -1)
        out["prev"] = (prev, prev, f"vs {prev:%b %Y}")
    elif period == "qtd":
        out["prev"] = (_shift(start, -3), _shift(asof, -3), "vs prior quarter")
    out["py"] = (*py, {"month": f"vs {py[1]:%b %Y}", "qtd": "vs same quarter last year",
                       "ytd": f"vs {asof.year - 1} same period", "12m": "vs prior 12 months"}[period])
    return out


def _where(filters: dict, skip: str | None = None) -> tuple[str, list]:
    sql, params = "", []
    for d, v in filters.items():
        if d != skip:
            sql += f' and "{d}" is not distinct from ?'
            params.append(v)
    return sql, params


def _by_window(name: str, exprs: dict, wins: dict, filters: dict, group: str | None = None):
    """Each expression over each window, optionally by one dimension: {(window, group value): {alias: value}}."""
    cols = ", ".join(f'{e} as "{a}"' for a, e in exprs.items())
    flt, fp = _where(filters, skip=group)
    g = f'"{group}", ' if group else "null as _g, "
    parts, params = [], []
    for key, (start, end, _) in wins.items():
        parts.append(f"select '{key}' as _w, {g}{cols}\nfrom marts.dashboard_cube\n"
                     f"where _cube = ? and metric_time__month between ? and ?{flt}"
                     + (f'\ngroup by "{group}"' if group else ""))
        params += [name, start, end, *fp]
    sql = "\nunion all\n".join(parts)
    _, rows = _read(sql, params, limit=DASH_LIMIT)
    return {(r[0], r[1]): dict(zip(exprs, r[2:])) for r in rows}, sql, params


def _series(name: str, exprs: dict, filters: dict, start: dt.date, end: dt.date, group: str | None = None):
    """Each expression by month (and by one dimension): {group value: {alias: {month: value}}}."""
    cols = ", ".join(f'{e} as "{a}"' for a, e in exprs.items())
    flt, fp = _where(filters, skip=group)
    g = f'"{group}"' if group else "null"
    _, rows = _read(f"select {g} as _g, metric_time__month, {cols} from marts.dashboard_cube "
                    f"where _cube = ? and metric_time__month between ? and ?{flt} group by 1, 2",
                    [name, start, end, *fp], limit=DASH_LIMIT * 4)
    out: dict = {}
    for r in rows:
        for a, v in zip(exprs, r[2:]):
            out.setdefault(r[0], {}).setdefault(a, {})[r[1]] = v
    return out


def _source(metric: str, name: str, filters: dict) -> str | None:
    """The cube a fixed metric can be read from at this page's filters: exactly that grain, or nothing."""
    cube = _cube()
    want = {MONTH, *filters}
    if set(cube.cubes[name]["dims"]) == want:
        return name
    return next((n for n, c in cube.cubes.items() if metric in c["metrics"] and set(c["dims"]) == want), None)


def _sql_text(sql: str, params: list) -> str:
    for p in params:
        sql = sql.replace("?", "null" if p is None else f"'{p}'", 1)
    return sql


def page(name: str, metric: str | None, period: str, today: dt.date, asof: dt.date | None = None,
         filters: dict | None = None, dim: str | None = None) -> dict:
    """One saved query as a report page: cards with comparisons, a trend, breakdowns and a table.

    Every number is one of the three Power BI measure templates over the
    cube's rows - filtered, grouped, never re-derived here.
    """
    import os

    cube = _cube()
    c = cube.cubes[name]
    current = today.replace(day=1)
    others = [d for d in c["dims"] if d != MONTH]
    filters = {d: v for d, v in (filters or {}).items() if d in others}
    metric = metric if metric in c["metrics"] else c["metrics"][0]
    _, rows = _read("select distinct metric_time__month from marts.dashboard_cube where _cube = ? "
                    "and metric_time__month <= ? order by 1 desc limit 36", [name, current])
    available = [dt.date.fromisoformat(r[0]) for r in rows]
    if asof not in available:
        asof = next((m for m in available if m < current), current)
    partial = asof == current
    wins = _windows(period, asof)
    first_cmp = "prev" if "prev" in wins else "py"
    additive = [m for m in c["metrics"] if _kind(m) != "fixed"]
    fixed = [m for m in c["metrics"] if _kind(m) == "fixed"]

    # Cards: every additive metric, and the volume behind each ratio, over each window.
    exprs = {m: _expr(m) for m in additive}
    for m in additive:
        if _kind(m) == "ratio":
            exprs[f"{m}__base"] = _weight(m)
    totals, card_sql, card_params = _by_window(name, exprs, wins, filters) if exprs else ({}, "", [])

    # Monthly series: two years back, for the sparklines, the trend and last year's line.
    trend_start = min(_shift(current, -11), wins["cur"][0])
    series_start = min(_shift(trend_start, -12), wins["py"][0])
    sources = {m: _source(m, name, filters) for m in fixed}
    series = _series(name, {m: _expr(m) for m in additive + [m for m in fixed if sources[m] == name]},
                     filters, series_start, current).get(None, {})
    for src in {s for s in sources.values() if s and s != name}:
        own = {d: v for d, v in filters.items() if d in cube.cubes[src]["dims"]}
        series.update(_series(src, {m: _expr(m) for m in fixed if sources[m] == src}, own,
                              series_start, current).get(None, {}))

    def at(m, month):
        return series.get(m, {}).get(month.isoformat())

    def latest(m) -> dt.date | None:
        """A fixed metric's most recent month at or before the as-of month (forecasts lag a month)."""
        return max((dt.date.fromisoformat(k) for k, v in series.get(m, {}).items()
                    if v is not None and k <= asof.isoformat()), default=None)

    spark_end = min(asof, _shift(current, -1))
    spark_months = [_shift(spark_end, -i) for i in range(11, -1, -1)]
    cards = []
    for m in c["metrics"]:
        card = {"metric": m, "spark": [at(m, k) for k in spark_months], "note": None, "base": None}
        if _kind(m) != "fixed":
            card["value"] = totals.get(("cur", None), {}).get(m)
            card["base"] = totals.get(("cur", None), {}).get(f"{m}__base")
            # A sum over a month still in progress is not comparable with a whole one.
            card["cmp"] = {k: None if partial and _kind(m) == "sum" else totals.get((k, None), {}).get(m)
                           for k in wins if k != "cur"}
        else:
            last = latest(m)
            card["value"] = at(m, last) if last else None
            card["cmp"] = {"prev": at(m, _shift(last, -1)) if last else None,
                           "py": at(m, _shift(last, -12)) if last else None}
            card["as_of"] = last.isoformat() if last else None
            if not sources[m]:
                card["note"] = ("No saved query holds this metric at the selected filters, so it is blank - "
                                "never an average of the rows below.")
            else:
                card["note"] = f"{last:%b %Y} value; it does not add up across months" if last else None
                if sources[m] != name:
                    card["note"] = f"Company-wide, from the {_title(sources[m])} cube. " + (card["note"] or "")
        cards.append(card)

    # Trend: the selected metric by month, with the same months a year earlier.
    trend_months = []
    k = trend_start
    while k <= current:
        trend_months.append(k)
        k = _shift(k, 1)
    trend = {"months": [k.isoformat() for k in trend_months], "values": [at(metric, k) for k in trend_months],
             "prior": [at(metric, _shift(k, -12)) for k in trend_months], "partial": current.isoformat()}
    if not any(v is not None for v in trend["values"]):
        trend["note"] = "No saved query holds this metric at the selected filters." if _kind(metric) == "fixed" \
            else "No data for these filters."

    breakdown = heatmap = table = matrix = None
    dim = dim if dim in others else (others[0] if others else None)
    if dim and additive:
        # Every additive metric by the breakdown dimension: the bars, and the scorecard table.
        g_exprs = {m: _expr(m) for m in additive}
        if _kind(metric) != "fixed":
            g_exprs["_weight"] = _weight(metric)
        grouped, _, _ = _by_window(name, g_exprs, {k: wins[k] for k in ("cur", first_cmp)}, filters, group=dim)
        labels = sorted({g for (_, g) in grouped}, key=lambda g: -(grouped.get(("cur", g), {}).get("_weight") or 0))
        table = {"dim": dim, "label": _dim_label(dim), "metrics": additive,
                 "rows": [{"label": g, "cur": grouped.get(("cur", g), {}), "cmp": grouped.get((first_cmp, g), {})}
                          for g in labels],
                 "total": {"cur": totals.get(("cur", None), {}), "cmp": totals.get((first_cmp, None), {})}}
        if dim in filters:
            # The bars keep every member of their own dimension and highlight the selection, as Power BI does.
            whole, _, _ = _by_window(name, {m: _expr(m) for m in additive},
                                     {k: wins[k] for k in ("cur", first_cmp)},
                                     {d: v for d, v in filters.items() if d != dim})
            table["total"] = {"cur": whole.get(("cur", None), {}), "cmp": whole.get((first_cmp, None), {})}
        if _kind(metric) != "fixed":
            span = {"trend": (trend_start, current, "")}
            volume, _, _ = _by_window(name, {"w": _weight(metric)}, span, filters, group=dim)
            top = sorted(labels, key=lambda g: -(volume.get(("trend", g), {}).get("w") or 0))[:12]
            by_member = _series(name, {"v": _expr(metric)}, filters, trend_start, current, group=dim)
            overall = series if dim not in filters else _series(
                name, {metric: _expr(metric)}, {d: v for d, v in filters.items() if d != dim},
                trend_start, current).get(None, {})
            heatmap = {"dim": dim, "label": _dim_label(dim), "months": trend["months"],
                       "rows": [{"label": g, "values": [by_member.get(g, {}).get("v", {}).get(k)
                                                        for k in trend["months"]]} for g in top],
                       "overall": [overall.get(metric, {}).get(k) for k in trend["months"]],
                       "more": max(len(labels) - len(top), 0)}
            breakdown = {"dim": dim, "label": _dim_label(dim), "basis": cube.label(cube.rollups[metric]["denominator"])
                         if _kind(metric) == "ratio" else None}
    if _kind(metric) == "fixed" and others:
        # A fixed metric only exists at the cube's full grain: show that grain, at its latest month.
        _, r = _read(f'select max(metric_time__month) from marts.dashboard_cube where _cube = ? '
                     f'and "{metric}" is not null and metric_time__month <= ?', [name, asof])
        if r[0][0]:
            month = dt.date.fromisoformat(r[0][0])
            dims = ", ".join(f'"{d}"' for d in others)
            flt, fp = _where(filters)
            _, rows_m = _read(f"select {dims}, {_expr(metric)} as v from marts.dashboard_cube "
                              f"where _cube = ? and metric_time__month = ?{flt} group by {dims} order by {dims}",
                              [name, month, *fp], limit=DASH_LIMIT)
            matrix = {"dims": [{"id": d, "label": _dim_label(d)} for d in others], "month": f"{month:%B %Y}",
                      "rows": rows_m, "company": at(metric, month)}

    months_opts = [{"value": m.isoformat(), "label": f"{m:%b %Y}" + (" (to date)" if m == current else "")}
                   for m in available[:24]]
    opts = {}
    for d in others:
        _, vals = _read(f'select distinct "{d}" from marts.dashboard_cube where _cube = ? order by 1 nulls last',
                        [name], limit=DASH_LIMIT)
        opts[d] = [v[0] for v in vals]
    days_in = (_shift(current, 1) - current).days
    return {"page": name, "metric": metric, "period": period, "asof": asof.isoformat(), "months": months_opts,
            "window": {"start": wins["cur"][0].isoformat(), "end": asof.isoformat(), "label": wins["cur"][2],
                       "partial": partial, "progress": f"{today.day} of {days_in} days" if partial else None},
            "comparisons": [{"key": k, "label": wins[k][2]} for k in wins if k != "cur"],
            "first_cmp": first_cmp, "filters": filters, "filter_options": opts, "dim": dim,
            "cards": cards, "spark_months": [k.isoformat() for k in spark_months], "trend": trend, "breakdown": breakdown, "heatmap": heatmap, "table": table,
            "matrix": matrix, "sql": _sql_text(card_sql, card_params),
            "refreshed": dt.datetime.fromtimestamp(os.path.getmtime(settings.warehouse_path)).isoformat(
                timespec="minutes")}


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
