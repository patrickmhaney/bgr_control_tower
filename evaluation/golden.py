"""Run, check and freeze the golden answers.

    python -m evaluation.golden check            # semantic layer == reference SQL == expected
    python -m evaluation.golden check --backend tsql
    python -m evaluation.golden check --live     # after `as_of`: semantic layer == reference SQL only
    python -m evaluation.golden freeze           # write today's answers as expected (review the diff!)

See evaluation/golden_answers.yml for what the file is and why.
"""
from __future__ import annotations

import argparse
import datetime as dt
import math
import os
import sys

import duckdb
import yaml

from core.settings import settings

HERE = os.path.dirname(os.path.abspath(__file__))
GOLDEN = os.path.join(HERE, "golden_answers.yml")


def _norm(v):
    if isinstance(v, (dt.datetime, dt.date)):
        return v.isoformat()[:10]
    if isinstance(v, str) and len(v) >= 10 and v[4] == "-" and v[7] == "-":
        return v[:10]
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return v


def _rows_to_map(rows: list, n_dims: int) -> dict:
    out = {}
    for r in rows:
        r = [_norm(v) for v in r]
        out["|".join("" if v is None else str(v) for v in r[:n_dims])] = r[n_dims:]
    return out


def _close(a, b, tol) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, float) or isinstance(b, float):
        if isinstance(a, float) and math.isnan(a):
            return isinstance(b, float) and math.isnan(b)
        return abs(float(a) - float(b)) <= tol * max(1.0, abs(float(a)), abs(float(b)))
    return a == b


def _maps_equal(x: dict, y: dict, tol: float) -> str | None:
    if set(x) != set(y):
        missing, extra = sorted(set(y) - set(x))[:3], sorted(set(x) - set(y))[:3]
        return f"different keys: missing {missing}, extra {extra}"
    for k in x:
        for a, b in zip(x[k], y[k], strict=True):
            if not _close(a, b, tol):
                return f"at {k!r}: {a} != {b}"
    return None


def reference(con, q: dict) -> dict:
    rows = con.execute(q["reference_sql"]).fetchall()
    return _rows_to_map(rows, len(q.get("group_by") or []))


def semantic(svc, q: dict) -> dict:
    group_by = q.get("group_by") or []
    res = svc.query(q["metrics"], group_by=group_by, where=q.get("where"), limit=None)
    cols = res["columns"]
    dims = [cols.index(g) for g in group_by]
    mets = [cols.index(m) for m in q["metrics"]]
    rows = [[r[i] for i in dims] + [r[i] for i in mets] for r in res["rows"]]
    return _rows_to_map(rows, len(group_by))


def run(mode: str, backend: str = "duckdb", frozen: bool = True) -> int:
    from serving.semantic_service import MetricRequestError, SemanticService

    with open(GOLDEN) as fh:
        doc = yaml.safe_load(fh)
    tol = float(doc.get("tolerance", 1e-6))
    provider = settings.mdm_provider
    svc = SemanticService(backend=backend)
    con = duckdb.connect(settings.warehouse_path, read_only=True)
    failures = 0
    try:
        for q in doc["queries"]:
            qid = q["id"]
            if "expect_refusal" in q:
                try:
                    svc.query(q["metrics"], group_by=q.get("group_by"), limit=None)
                    print(f"FAIL {qid}: answered, should have been refused")
                    failures += 1
                except MetricRequestError as exc:
                    ok = q["expect_refusal"] in str(exc)
                    print(f"{'ok  ' if ok else 'FAIL'} {qid}: refused")
                    failures += 0 if ok else 1
                continue
            ref = reference(con, q)
            if mode == "freeze":
                frozen = [[k, *v] for k, v in sorted(ref.items())]
                if q.get("mdm_sensitive"):
                    q.setdefault("expected_by_provider", {})[provider] = frozen
                    q.pop("expected", None)
                else:
                    q["expected"] = frozen
                continue
            sem = semantic(svc, q)
            problem = _maps_equal(sem, ref, tol)
            expected = (q.get("expected_by_provider", {}).get(provider)
                        if q.get("mdm_sensitive") else q.get("expected"))
            if problem is None and expected is not None and frozen:
                exp = {row[0]: row[1:] for row in expected}
                problem = _maps_equal(sem, exp, tol)
                if problem:
                    problem = "differs from the frozen answer " + problem
            print(f"{'ok  ' if problem is None else 'FAIL'} {qid}" + (f": {problem}" if problem else ""))
            failures += 0 if problem is None else 1
    finally:
        con.close()
    if mode == "freeze":
        header = open(GOLDEN).read().split("\nversion:")[0]
        with open(GOLDEN, "w") as fh:
            fh.write(header + "\n")
            yaml.safe_dump(doc, fh, sort_keys=False, width=100)
        print(f"Froze {len(doc['queries'])} golden answers for MDM provider {provider}.")
        return 0
    print(f"\n{len(doc['queries']) - failures} of {len(doc['queries'])} golden answers pass.")
    return 1 if failures else 0


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m evaluation.golden")
    p.add_argument("mode", choices=["check", "freeze"])
    p.add_argument("--backend", choices=["duckdb", "tsql"], default="duckdb")
    p.add_argument("--live", action="store_true",
                   help="skip the frozen answers, which hold only for the sources as of `as_of`")
    a = p.parse_args()
    sys.exit(run(a.mode, a.backend, frozen=not a.live))


if __name__ == "__main__":
    main()
