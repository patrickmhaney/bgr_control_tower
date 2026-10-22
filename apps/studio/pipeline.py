"""The pipeline as the Studio walks it: each step is one or more step commands.

Every command is a `python -m ...` invocation of the platform's own step
commands (ctl/__main__.py), the same ones `make run`, Dagster and CI call. The
Studio adds nothing to the pipeline; it runs it one step at a time and reads
what happened (apps/studio/probe.py).
"""
from __future__ import annotations

import re

STEPS = [
    {"id": "day", "title": "A day of business", "node": "sources",
     "lead": "The source systems take orders, ship, invoice and work deals - one simulated day.",
     "commands": [["ctl", "sources", "advance", "--days", "1"]]},
    {"id": "collect", "title": "Collect the changes", "node": "ingestion", "checks": ["C2"],
     "lead": "Pick up only what changed in each system - deletes included - and add it to the raw history.",
     "commands": [["ctl", "ingest", "--reconcile"], ["ctl", "build", "--stage", "raw"]]},
    {"id": "clean", "title": "Clean", "node": "transformation", "checks": ["quality"],
     "lead": "Standardise names, dates and codes into one tidy table per source table, with quality tests.",
     "commands": [["ctl", "build", "--stage", "clean"]]},
    {"id": "match", "title": "Match customers and people", "node": "mdm", "checks": ["C3"],
     "lead": "Recognise the same customer in X3 and HubSpot, and the same person, and give each one ID.",
     "commands": [["ctl", "build", "--stage", "mdm", "--provider", "{provider}"]]},
    {"id": "model", "title": "Build the star schema", "node": "warehouse", "checks": ["C4"],
     "lead": "Assemble the fact and dimension tables every metric reads from.",
     "commands": [["ctl", "build", "--stage", "model"]]},
    {"id": "metrics", "title": "Compute the metrics", "node": "semantic", "checks": ["C5", "C7"],
     "lead": "The semantic layer computes every metric from its one definition, into the tables Power BI reads.",
     "commands": [["ctl", "materialize"]]},
    {"id": "serve", "title": "Serve every channel", "node": "api", "checks": ["C6"],
     "lead": "Publish the metrics to the serving database, the API and the AI tools.",
     "commands": [["ctl", "serve-load"]]},
]

BY_ID = {s["id"]: s for s in STEPS}

#: Back to day 0: delete the data directory and set the sources up again.
RESET = {"id": "reset", "title": "Reset to day 0",
         "commands": [["ctl", "reset"], ["ctl", "sources", "init"]]}

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
                out.append({"label": "X3 changes captured by CDC", "raw": int(m.group(2).replace(",", "")),
                            "fmt": "int"})
    if step == "collect":
        # X3's rows are broken down by kind of change in the probe.
        names = {"hubspot": "HubSpot rows - changes, plus a check for deletes",
                 "netstock": "Netstock rows - a full copy, as it has no change feed",
                 "azure_cost": "Cloud cost rows"}
        for line in lines:
            m = re.match(r"(hubspot|netstock|azure_cost)\s+([\d,]+) rows", line)
            if m:
                out.append({"label": names[m.group(1)], "raw": int(m.group(2).replace(",", "")),
                            "fmt": "int"})
    return out
