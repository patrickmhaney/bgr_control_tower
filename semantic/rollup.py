"""How each metric rolls up once it is stored in a pre-aggregated table.

A saved query stores every metric at one grain. Anything that reads the
stored rows at a coarser grain - a Power BI visual, an app summing a mart -
has to re-aggregate them, and that is only correct for some metrics:

    sum     a sum or count: add the stored values up
    ratio   a ratio of two sums: add up the numerator and the denominator,
            then divide. The materializer stores both components beside the
            ratio so this is possible.
    fixed   everything else (distinct counts, averages, derived and cumulative
            metrics, ratios over filtered or non-additive parts): correct
            only at the grain it was stored at, never re-aggregated

The classification is read from the semantic manifest, so there is nothing to
declare: a new metric gets the right behaviour from its definition.
"""
from __future__ import annotations

import json
import re

ADDITIVE_AGGS = {"sum", "count"}


def _ref(ref) -> str:
    return ref["name"] if isinstance(ref, dict) else ref


def classify(semantic_manifest: dict) -> dict[str, dict]:
    """{metric: {"kind": "sum"} | {"kind": "ratio", "numerator", "denominator"} | {"kind": "fixed"}}"""
    aggs = {ms["name"]: ms["agg"].lower()
            for sm in semantic_manifest["semantic_models"] for ms in sm.get("measures", [])}
    metrics = {m["name"]: m for m in semantic_manifest["metrics"]}
    out: dict[str, dict] = {}

    def kind(name: str) -> dict:
        if name in out:
            return out[name]
        m = metrics[name]
        tp = m.get("type_params") or {}
        result = {"kind": "fixed"}
        if m["type"] == "simple":
            if aggs.get(_ref(tp.get("measure"))) in ADDITIVE_AGGS:
                result = {"kind": "sum"}
        elif m["type"] == "ratio":
            num, den = tp.get("numerator") or {}, tp.get("denominator") or {}
            plain = not m.get("filter") and not any(
                isinstance(r, dict) and (r.get("filter") or r.get("alias")) for r in (num, den))
            if (plain and kind(_ref(num))["kind"] == "sum"
                    and kind(_ref(den))["kind"] == "sum"):
                result = {"kind": "ratio", "numerator": _ref(num), "denominator": _ref(den)}
        out[name] = result
        return result

    for name in metrics:
        kind(name)
    return out


def group_by_names(saved_query: dict) -> list[str]:
    """A saved query's group_by as the names the semantic service takes."""
    names = []
    for g in saved_query["query_params"].get("group_by") or []:
        t = re.fullmatch(r"TimeDimension\('(\w+)',\s*'(\w+)'\)", g.strip())
        d = re.fullmatch(r"Dimension\('(\w+)'\)", g.strip())
        if t:
            names.append(f"{t[1]}__{t[2]}")
        elif d:
            names.append(d[1])
        else:
            raise ValueError(f"saved query {saved_query['name']}: unsupported group_by {g!r}")
    return names


def cube_columns(saved_query: dict, rollups: dict[str, dict]) -> list[str]:
    """The metric columns a saved query stores: its metrics, then the ratio components."""
    cols = list(saved_query["query_params"]["metrics"])
    for m in saved_query["query_params"]["metrics"]:
        r = rollups[m]
        if r["kind"] == "ratio":
            cols += [c for c in (r["numerator"], r["denominator"]) if c not in cols]
    return cols


def load(path: str) -> tuple[dict, dict[str, dict]]:
    with open(path) as fh:
        sm = json.load(fh)
    return sm, classify(sm)
