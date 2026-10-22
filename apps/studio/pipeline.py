"""The pipeline as the Studio walks it: each step is one or more step commands.

Every command is a `python -m ...` invocation of the platform's own step
commands (ctl/__main__.py), the same ones `make run`, Dagster and CI call. The
Studio adds nothing to the pipeline; it runs it one step at a time and reads
what happened (apps/studio/probe.py).
"""
from __future__ import annotations

import re

STEPS = [
    {"id": "day", "title": "Advance one day", "node": "sources",
     "lead": "Advance the simulated source systems by one business day.",
     "commands": [["ctl", "sources", "advance", "--days", "1"]]},
    {"id": "collect", "title": "Collect", "node": "ingestion", "checks": ["C2"],
     "lead": "Extract changes from each source and append them to raw storage.",
     "commands": [["ctl", "ingest", "--reconcile"], ["ctl", "build", "--stage", "raw"]]},
    {"id": "clean", "title": "Clean", "node": "transformation", "checks": ["quality"],
     "lead": "Build the staging tables and run their data tests.",
     "commands": [["ctl", "build", "--stage", "clean"]]},
    {"id": "match", "title": "Match", "node": "mdm", "checks": ["C3"],
     "lead": "Match customers and employees across systems and assign golden IDs.",
     "commands": [["ctl", "build", "--stage", "mdm", "--provider", "{provider}"]]},
    {"id": "model", "title": "Model", "node": "warehouse", "checks": ["C4"],
     "lead": "Build the fact and dimension tables.",
     "commands": [["ctl", "build", "--stage", "model"]]},
    {"id": "metrics", "title": "Compute metrics", "node": "semantic", "checks": ["C5", "C7"],
     "lead": "Compute the saved queries through the semantic layer into the marts and the Power BI table.",
     "commands": [["ctl", "materialize"]]},
    {"id": "serve", "title": "Serve", "node": "api", "checks": ["C6"],
     "lead": "Load the marts into the serving database and test the API.",
     "commands": [["ctl", "serve-load"]]},
]

BY_ID = {s["id"]: s for s in STEPS}

#: Back to day 0: delete the data directory, set the sources up again and run
#: the pipeline once, so every step has data to work on. It records no step
#: results: the strip starts grey and turns green only as steps are run.
RESET = {"id": "reset", "title": "Reset to day 0",
         "commands": [["ctl", "reset"], ["ctl", "sources", "init"], ["ctl", "run", "--reconcile"]]}

ANSI = re.compile(r"\x1b\[[0-9;]*m")
DBT_TIME = re.compile(r"^\d\d:\d\d:\d\d\s+")
DBT_PROGRESS = re.compile(r"\b(\d+) of (\d+) (START|OK|PASS|WARN|ERROR|FAIL|SKIP)")


def clean_line(line: str) -> str:
    return DBT_TIME.sub("", ANSI.sub("", line)).rstrip()


def progress(line: str) -> tuple[int, int] | None:
    """dbt's 'N of M OK ...' lines, as a fraction done."""
    m = DBT_PROGRESS.search(line)
    if m and m.group(3) != "START":
        return int(m.group(1)), int(m.group(2))
    return None


def facts_from_log(step: str, lines: list[str]) -> list[dict]:
    """What a step printed that is worth a number on screen."""
    out = []
    if step == "day":
        for line in lines:
            m = re.match(r"(\d{4}-\d\d-\d\d): ([\d,]+) change rows captured", line)
            if m:
                out.append({"label": "X3 CDC change rows", "raw": int(m.group(2).replace(",", "")),
                            "fmt": "int"})
    if step == "collect":
        # X3's rows are broken down by kind of change in the probe.
        names = {"hubspot": "HubSpot rows (changes and delete check)",
                 "netstock": "Netstock rows (full snapshot)",
                 "azure_cost": "Cloud cost rows"}
        for line in lines:
            m = re.match(r"(hubspot|netstock|azure_cost)\s+([\d,]+) rows", line)
            if m:
                out.append({"label": names[m.group(1)], "raw": int(m.group(2).replace(",", "")),
                            "fmt": "int"})
    return out
