"""A contract's definition files and test suites, as the Studio shows and runs them.

Each suite in content.yml is one of the platform's own checks. This module
turns it into the command to run, lists its cases before it runs (so the
screen can show what is about to be tested), and reads each case's result
from the command's output as it streams.
"""
from __future__ import annotations

import ast
import json
import os
import re

import yaml

from core.settings import ROOT

TARGET = os.path.join(ROOT, "transform", "target")


ACRONYMS = {"dso": "DSO", "mdm": "MDM", "api": "API", "mcp": "MCP", "x3": "X3", "sql": "SQL",
            "tsql": "T-SQL", "openapi": "OpenAPI", "crm": "CRM", "erp": "ERP", "otd": "OTD"}


def _label(name: str) -> str:
    words = re.sub(r"^test_", "", name).split("_")
    words = [ACRONYMS.get(w, w) for w in words]
    return " ".join(words)[:1].upper() + " ".join(words)[1:]


def _needs_sql_server(fn: ast.FunctionDef) -> bool:
    return any(isinstance(d, ast.Attribute) and d.attr == "tsql" for d in fn.decorator_list)


def excerpt(spec: dict) -> dict:
    """The lines of a definition file the Studio shows."""
    path = os.path.join(ROOT, spec["path"])
    with open(path) as fh:
        lines = fh.read().splitlines()
    start = 0
    if spec.get("from"):
        start = next((i for i, ln in enumerate(lines) if ln.startswith(spec["from"])), 0)
    count = spec.get("lines", 80)
    return {"path": spec["path"], "start": start + 1, "total": len(lines),
            "text": "\n".join(lines[start:start + count])}


def command(suite: dict, live: bool) -> list[str]:
    """The `python -m ...` arguments for a suite."""
    kind = suite["kind"]
    if kind == "pytest":
        args = ["pytest", "-v", "-p", "no:cacheprovider", "--no-header", "-o", "console_output_style=classic",
                suite["path"]]
        if suite.get("exclude"):
            args += ["-k", " and ".join(f"not {n}" for n in suite["exclude"])]
        return args
    if kind == "dbt":
        return ["ctl", "dbt", "test", "--select", suite["select"]]
    if kind == "verify":
        return ["ingestion.verify"]
    if kind == "golden":
        return ["evaluation.golden", "check"] + (["--live"] if live else [])
    if kind == "parity":
        return ["serving.powerbi_parity", "local"] + (["--live"] if live else [])
    raise ValueError(kind)


def cases(suite: dict) -> list[dict]:
    """What the suite will test, before it runs. Empty when only the run can tell."""
    kind = suite["kind"]
    if kind == "pytest":
        with open(os.path.join(ROOT, suite["path"])) as fh:
            tree = ast.parse(fh.read())
        skip = set(suite.get("exclude") or [])
        return [{"name": n.name, "label": _label(n.name)} for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")
                and n.name not in skip and not _needs_sql_server(n)]
    if kind == "golden":
        from evaluation.golden import GOLDEN

        with open(GOLDEN) as fh:
            return [{"name": q["id"], "label": _label(q["id"])} for q in yaml.safe_load(fh)["queries"]]
    if kind == "parity":
        from serving.powerbi_parity import OUT

        with open(OUT) as fh:
            return [{"name": q["id"], "label": _label(q["id"]), "detail": q["cube"]} for q in json.load(fh)]
    if kind == "dbt":
        try:
            with open(os.path.join(TARGET, "manifest.json")) as fh:
                nodes = json.load(fh)["nodes"]
        except OSError:
            return []
        gold = {k for k, n in nodes.items() if n["resource_type"] == "model" and n["schema"].endswith("gold")}
        return [{"name": n["name"], "label": n["name"]} for n in nodes.values()
                if n["resource_type"] == "test" and gold & set(n["depends_on"]["nodes"])]
    return []


PYTEST = re.compile(r"::(\w+) (PASSED|FAILED|SKIPPED|ERROR)")
DBT = re.compile(r"\b\d+ of \d+ (PASS|FAIL|WARN|ERROR) (\S+)")
OK_FAIL = re.compile(r"^(ok  |FAIL) (\S+?)(?: \((\S+)\))?(?::\s*(.*))?$")


def parse(kind: str, line: str) -> dict | None:
    """One case's result, if this output line reports one."""
    if kind == "pytest":
        m = PYTEST.search(line)
        if m:
            status = {"PASSED": "pass", "SKIPPED": "skip"}.get(m.group(2), "fail")
            return {"name": m.group(1), "label": _label(m.group(1)), "status": status}
    elif kind == "dbt":
        m = DBT.search(line)
        if m:
            status = {"PASS": "pass", "WARN": "warn"}.get(m.group(1), "fail")
            return {"name": m.group(2), "label": m.group(2), "status": status}
    else:
        m = OK_FAIL.match(line)
        if m:
            name = m.group(2)
            label = name if kind == "verify" else _label(name)
            return {"name": name, "label": label, "status": "pass" if m.group(1) == "ok  " else "fail",
                    "detail": m.group(4) or m.group(3) or ""}
    return None
