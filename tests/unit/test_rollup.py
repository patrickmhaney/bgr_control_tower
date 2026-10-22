"""Rollup classification and the three Power BI measure templates."""
from semantic.rollup import classify, cube_columns, group_by_names
from serving.powerbi import measure_dax, measure_sql


def _manifest(metrics, aggs):
    return {"semantic_models": [{"measures": [{"name": n, "agg": a} for n, a in aggs.items()]}],
            "metrics": metrics}


MANIFEST = _manifest(
    [
        {"name": "lines", "type": "simple", "type_params": {"measure": {"name": "lines"}}},
        {"name": "late", "type": "simple", "type_params": {"measure": {"name": "late"}},
         "filter": {"where_filters": [{"where_sql_template": "x"}]}},
        {"name": "customers", "type": "simple", "type_params": {"measure": {"name": "customers"}}},
        {"name": "late_rate", "type": "ratio",
         "type_params": {"numerator": {"name": "late"}, "denominator": {"name": "lines"}}},
        {"name": "filtered_rate", "type": "ratio", "filter": {"where_filters": [{}]},
         "type_params": {"numerator": {"name": "late"}, "denominator": {"name": "lines"}}},
        {"name": "lines_per_customer", "type": "ratio",
         "type_params": {"numerator": {"name": "lines"}, "denominator": {"name": "customers"}}},
        {"name": "on_time_rate", "type": "derived", "type_params": {"expr": "1 - late_rate"}},
        {"name": "trailing_lines", "type": "cumulative", "type_params": {"measure": "lines"}},
    ],
    {"lines": "sum", "late": "count", "customers": "count_distinct"})


def test_classification():
    r = classify(MANIFEST)
    assert r["lines"]["kind"] == "sum"
    assert r["late"]["kind"] == "sum"                    # a filtered sum still adds up
    assert r["customers"]["kind"] == "fixed"             # distinct counts never add up
    assert r["late_rate"] == {"kind": "ratio", "numerator": "late", "denominator": "lines"}
    assert r["filtered_rate"]["kind"] == "fixed"         # the components alone would be wrong
    assert r["lines_per_customer"]["kind"] == "fixed"    # a non-additive denominator
    assert r["on_time_rate"]["kind"] == "fixed"
    assert r["trailing_lines"]["kind"] == "fixed"


def test_cube_stores_ratio_components():
    sq = {"name": "c", "query_params": {
        "metrics": ["late_rate", "customers"],
        "group_by": ["TimeDimension('metric_time', 'month')", "Dimension('site__site_name')"]}}
    assert group_by_names(sq) == ["metric_time__month", "site__site_name"]
    assert cube_columns(sq, classify(MANIFEST)) == ["late_rate", "customers", "late", "lines"]


def test_templates_are_guarded():
    r = classify(MANIFEST)
    assert measure_dax("lines", r["lines"]).startswith("IF(HASONEVALUE('dashboard_cube'[Cube])")
    assert "DIVIDE(SUM('dashboard_cube'[late]), SUM('dashboard_cube'[lines]))" in measure_dax(
        "late_rate", r["late_rate"])
    assert measure_dax("customers", r["customers"]) == (
        "IF(COUNTROWS('dashboard_cube') = 1, MAX('dashboard_cube'[customers]))")
    assert measure_sql("late_rate", r["late_rate"]) == 'sum("late") / nullif(sum("lines"), 0)'
