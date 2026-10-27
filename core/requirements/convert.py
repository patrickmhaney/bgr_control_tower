"""The one-time converter: a governance tool workspace -> a project's requirements.

    python -m core.requirements.convert PATH/requirements.db --workspace demo --project sample [--check]

Reads the governance tool's SQLite database directly (its spec export reduced
people to roles) and writes one workspace into one project: requirements/,
each measure's definition - label, description, owner, caveats - in the
semantic files, the seeds the requirements feed, and project.yml's slots and
business systems. The database is the truth for everything it held, so
running it again changes nothing.

Every column the database has is listed in COLUMNS with its new home or why
it is dropped, and a database with a column COLUMNS doesn't list is refused,
so nothing is lost without saying so. Files are edited through the store's
round-trip writers: an entry the conversion doesn't change keeps its bytes,
comments included. Nothing is committed: review the diff and commit it.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import shutil
import sqlite3

from ruamel.yaml.comments import CommentedMap

from core import project, requirements
from core.requirements import store

#: Every column of the governance tool's database: where it lives now, or why it is dropped.
COLUMNS: dict[str, dict[str, str]] = {
    "clients": {
        "id": "dropped: a database key",
        "slug": "dropped: chosen with --workspace; the project has its own slug",
        "name": "project.yml name (left as it is when they differ, and reported)",
        "slots": "project.yml slots",
        "sources": "project.yml business_systems, each mapped to an architecture system by name or type",
        "is_demo": "dropped: every project is a folder; none is special",
        "created_at": "dropped: git history",
        "target_slug": "dropped: there is no handoff; the requirements live in the project",
    },
    "people": {
        "id": "requirements/people.yml key (p1, p2, ... in id order)",
        "client_id": "dropped: one workspace is one project",
        "name": "requirements/people.yml name",
        "role": "requirements/people.yml role",
        "email": "requirements/people.yml email",
        "department_id": "requirements/people.yml department",
        "created_at": "dropped: git history",
    },
    "departments": {
        "id": "dropped: a database key; the code is the key",
        "client_id": "dropped: one workspace is one project",
        "name": "seeds/department.csv department_name",
        "code": "seeds/department.csv department_code",
        "position": "seeds/department.csv display_order",
    },
    "processes": {
        "id": "dropped: a database key; the code is the key",
        "client_id": "dropped: one workspace is one project",
        "position": "requirements/processes.yml order (seeds/process.csv display_order is generated from it)",
        "code": "requirements/processes.yml key",
        "name": "requirements/processes.yml name",
        "active": "requirements/processes.yml active",
        "answers": "requirements/processes.yml answers",
        "unknown": "requirements/processes.yml unknown",
        "owner_id": "requirements/processes.yml answers.owner.person",
        "owner_dept_id": "requirements/processes.yml answers.owner.department",
        "owner_note": "requirements/processes.yml answers.owner.note",
        "assignee_id": "requirements/processes.yml assignee",
        "status": "requirements/processes.yml interview",
        "followup": "requirements/processes.yml followup",
        "followup_note": "requirements/processes.yml followup_note",
        "notes": "requirements/processes.yml notes",
        "updated_at": "dropped: git history",
        "updated_by": "dropped: git history (the commit author)",
        "completed_at": "dropped: git history",
    },
    "process_steps": {
        "id": "dropped: a database key",
        "process_id": "requirements/processes.yml answers.steps of that process",
        "position": "requirements/processes.yml answers.steps order",
        "name": "requirements/processes.yml answers.steps[].name",
        "dept_id": "requirements/processes.yml answers.steps[].department",
        "person_id": "requirements/processes.yml answers.steps[].person",
        "system": "requirements/processes.yml answers.steps[].system",
    },
    "dimensions": {
        "id": "dropped: a database key; the code is the key",
        "client_id": "dropped: one workspace is one project",
        "position": "requirements/dimensions.yml order",
        "code": "requirements/dimensions.yml key",
        "name": "requirements/dimensions.yml name",
        "answers": "requirements/dimensions.yml answers",
        "unknown": "requirements/dimensions.yml unknown",
        "owner_id": "requirements/dimensions.yml answers.owner.person",
        "owner_dept_id": "requirements/dimensions.yml answers.owner.department",
        "owner_note": "requirements/dimensions.yml answers.owner.note",
        "assignee_id": "requirements/dimensions.yml assignee",
        "status": "requirements/dimensions.yml interview",
        "followup": "requirements/dimensions.yml followup",
        "followup_note": "requirements/dimensions.yml followup_note",
        "notes": "requirements/dimensions.yml notes",
        "updated_at": "dropped: git history",
        "updated_by": "dropped: git history (the commit author)",
        "completed_at": "dropped: git history",
    },
    "bus_cells": {
        "process_id": "requirements/bus_matrix.yml key",
        "dimension_id": "requirements/bus_matrix.yml dimension codes, in dimension order",
    },
    "dashboards": {
        "id": "dropped: a database key; the code is the key",
        "client_id": "dropped: one workspace is one project",
        "code": "requirements/dashboards.yml key",
        "name": "requirements/dashboards.yml name",
        "position": "requirements/dashboards.yml order",
        "audience": "requirements/dashboards.yml audience",
        "decisions": "requirements/dashboards.yml decisions",
        "cadence": "requirements/dashboards.yml cadence",
        "access": "requirements/dashboards.yml access",
    },
    "requirements": {
        "id": "dropped: a database key; the metric name is the key",
        "dashboard_id": "seeds/process_metric.csv process_code, or the dashboard in requirements/dashboards.yml slots",
        "slot": "seeds/process_metric.csv slot and display_order, or requirements/dashboards.yml slots key",
        "metric_name": "the metric's name: requirements/measures.yml key and the semantic files' name "
                       "(set from the label when it is empty)",
        "name": "the semantic files' label",
        "description": "the semantic files' description",
        "owner_id": "the semantic files' owner: that person's role",
        "owner_note": "the semantic files' owner, when no person is picked",
        "notes": "the semantic files' caveats, one per line (as the tool's compiler wrote them)",
        "formula": "requirements/measures.yml answers.formula",
        "sources": "requirements/measures.yml answers.sources",
        "source_other": "requirements/measures.yml answers.source_other",
        "target": "requirements/measures.yml answers.target",
        "target_none": "requirements/measures.yml answers.target_none",
        "report": "requirements/measures.yml answers.report",
        "report_none": "requirements/measures.yml answers.report_none",
        "breakdowns": "requirements/measures.yml answers.breakdowns",
        "breakdowns_same": "requirements/measures.yml answers.breakdowns_same",
        "dimension_ids": "requirements/measures.yml answers.dimensions",
        "time_basis": "requirements/measures.yml answers.time",
        "refresh": "requirements/measures.yml answers.refresh",
        "refresh_why": "requirements/measures.yml answers.refresh_why",
        "restatement": "requirements/measures.yml answers.restatement",
        "restatement_none": "requirements/measures.yml answers.restatement_none",
        "sme_id": "requirements/measures.yml answers.sme.person",
        "sme_note": "requirements/measures.yml answers.sme.note",
        "unknown": "requirements/measures.yml unknown",
        "assignee_id": "requirements/measures.yml assignee",
        "status": "requirements/measures.yml interview",
        "followup": "requirements/measures.yml followup",
        "followup_note": "requirements/measures.yml followup_note",
        "process_id": "requirements/measures.yml process, for a measure on no process dashboard; otherwise "
                      "its row in seeds/process_metric.csv says",
        "ref_id": "the slot shows the referred measure: a row in seeds/process_metric.csv or "
                  "requirements/dashboards.yml slots",
        "binding": "dropped: build logic. format and direction are already in metrics.yml meta, a backlog "
                   "measure's status, reason and unblock_requires in backlog.yml (used only to create a "
                   "backlog entry for a measure no semantic file has)",
        "updated_at": "dropped: git history",
        "updated_by": "dropped: git history (the commit author)",
        "completed_at": "dropped: git history",
    },
    "measure_departments": {
        "id": "dropped: a database key",
        "requirement_id": "seeds/department_metric.csv metric_name",
        "department_id": "seeds/department_metric.csv department_code",
        "process_id": "seeds/department_metric.csv process_code",
        "influence": "seeds/department_metric.csv influence",
        "position": "seeds/department_metric.csv row order",
    },
    "tiles": {
        "id": "dropped: a database key",
        "dashboard_id": "requirements/sketches.yml key",
        "kind": "requirements/sketches.yml kind",
        "x": "requirements/sketches.yml x", "y": "requirements/sketches.yml y",
        "w": "requirements/sketches.yml w", "h": "requirements/sketches.yml h",
        "title": "requirements/sketches.yml title",
        "requirement_id": "requirements/sketches.yml measure",
        "dimension_id": "requirements/sketches.yml dimension",
        "note": "requirements/sketches.yml note",
    },
    "cubes": {
        "id": "dropped: build logic, already in models/semantic/saved_queries.yml",
        "client_id": "dropped: build logic, already in models/semantic/saved_queries.yml",
        "position": "dropped: build logic, already in models/semantic/saved_queries.yml",
        "name": "dropped: build logic, already in models/semantic/saved_queries.yml",
        "description": "dropped: build logic, already in models/semantic/saved_queries.yml",
        "measures": "dropped: build logic, already in models/semantic/saved_queries.yml",
        "group_by": "dropped: build logic, already in models/semantic/saved_queries.yml",
    },
    "activity": {c: "dropped: the change history starts again in git with the conversion"
                 for c in ("id", "requirement_id", "at", "actor_id", "action", "detail")},
    "item_activity": {c: "dropped: the change history starts again in git with the conversion"
                      for c in ("id", "client_id", "kind", "item_id", "at", "actor_id", "action", "detail")},
    "archive": {c: "dropped: restore is undoing a commit now; archived items are reported, not converted"
                for c in ("id", "client_id", "kind", "label", "payload", "archived_at", "archived_by")},
}

#: The comment a requirements file starts with when the conversion creates it.
HEADERS = {
    "people": "# The people the requirements name, by id: who owns, who answers, who follows\n"
              "# up. The only file in the project with names in it; every other file refers\n"
              "# to a person by id. A metric's owner in the semantic files is a role, so\n"
              "# picking a person as owner writes their role.\n",
    "processes": "# Business processes, by code, in display order: the rows of the bus matrix.\n"
                 "# seeds/process.csv is generated from this file. Questions: core/requirements/questions.yml.\n",
    "dimensions": "# Dimensions, by code, in display order: what the business is measured by, and\n"
                  "# the columns of the bus matrix. Questions: core/requirements/questions.yml.\n",
    "bus_matrix": "# The bus matrix: each process and the dimensions it is analysed by.\n",
    "dashboards": "# Dashboards, by code, in display order: the rows of the Measures grid, and how\n"
                  "# each is used. A process dashboard (its code is a process code) takes its\n"
                  "# measures from seeds/process_metric.csv; any other lists them in `slots`.\n",
    "measures": "# Each measure's discovery answers, by metric name. Its label, description,\n"
                "# owner and caveats are its definition, in the semantic files\n"
                "# (models/semantic/metrics.yml, or backlog.yml until it has a formula).\n"
                "# Questions: core/requirements/questions.yml.\n",
    "sketches": "# Dashboard sketches, by dashboard code: tiles on a 12-column grid.\n"
                "# Tile kinds: core/requirements/questions.yml (tiles).\n",
}
INTERVIEW = {"not_started", "in_progress", "complete"}


class ConvertError(ValueError):
    pass


def _rows(conn, sql: str, *args) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, args)]


def _text(v) -> str:
    return (v or "").strip() if isinstance(v, str) else v


def _clean(d: dict) -> dict:
    """Leave out what the files leave out: empty values and defaults."""
    return {k: v for k, v in d.items() if not store._empty(k, v)}


def _snake(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def coverage_problems(conn) -> list[str]:
    """Columns in the database that COLUMNS doesn't list, and the other way round."""
    out = []
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
    for t in tables:
        have = [r[1] for r in conn.execute(f"PRAGMA table_info({t})")]
        listed = COLUMNS.get(t)
        if listed is None:
            out.append(f"table {t}: not in COLUMNS")
            continue
        out += [f"{t}.{c}: not in COLUMNS" for c in have if c not in listed]
        out += [f"{t}.{c}: in COLUMNS but not in the database" for c in listed if c not in have]
    out += [f"table {t}: in COLUMNS but not in the database" for t in COLUMNS if t not in tables]
    return out


# --------------------------------------------------------------- reading --

class Workspace:
    """One workspace of the governance tool's database, as the project files hold it."""

    def __init__(self, conn: sqlite3.Connection, slug: str):
        conn.row_factory = sqlite3.Row
        problems = coverage_problems(conn)
        if problems:
            raise ConvertError("the database has columns this converter doesn't know: " + "; ".join(problems))
        found = _rows(conn, "SELECT * FROM clients WHERE slug = ?", slug)
        if not found:
            known = ", ".join(r["slug"] for r in _rows(conn, "SELECT slug FROM clients ORDER BY id"))
            raise ConvertError(f"no workspace {slug!r} (there are: {known})")
        self.conn, self.client = conn, found[0]
        self.notes: list[str] = []
        cid = self.client["id"]

        self.departments = _rows(conn, "SELECT * FROM departments WHERE client_id = ? "
                                       "ORDER BY COALESCE(position, 1000000), id", cid)
        self.dept = {d["id"]: d["code"] or re.sub(r"[^A-Z0-9]+", "_", d["name"].upper()).strip("_")
                     for d in self.departments}
        self.people_rows = _rows(conn, "SELECT * FROM people WHERE client_id = ? ORDER BY id", cid)
        self.person = {p["id"]: f"p{i}" for i, p in enumerate(self.people_rows, 1)}
        self.role = {p["id"]: (p["role"] or "").strip() for p in self.people_rows}

        def named(table: str, code_of) -> list[dict]:
            out = []
            for r in _rows(conn, f"SELECT * FROM {table} WHERE client_id = ? ORDER BY position, id", cid):
                if not _text(r["name"]):
                    if r["code"] or r["answers"] not in ("", "{}") or r["notes"]:
                        self.notes.append(f"{table}: skipped an unnamed row with content (id {r['id']})")
                    continue
                r["key"] = r["code"] or code_of(r["name"])
                out.append(r)
            return out

        self.process_rows = named("processes", lambda n: re.sub(r"[^A-Z0-9]+", "", n.upper()))
        self.dimension_rows = named("dimensions", _snake)
        self.proc = {r["id"]: r["key"] for r in self.process_rows}
        self.dim = {r["id"]: r["key"] for r in self.dimension_rows}
        self.dashboard_rows = _rows(conn, "SELECT * FROM dashboards WHERE client_id = ? ORDER BY position, id", cid)
        self.dash = {d["id"]: d["code"] for d in self.dashboard_rows}
        self.cells = _rows(conn, "SELECT r.* FROM requirements r JOIN dashboards d ON d.id = r.dashboard_id "
                                 "WHERE d.client_id = ? ORDER BY d.position, r.slot", cid)
        self.by_id = {r["id"]: r for r in self.cells}
        #: requirement id -> metric name, for each cell that defines a measure
        self.metric = {r["id"]: r["metric_name"] or store.metric_name(r["name"])
                       for r in self.cells if _text(r["name"]) and r["ref_id"] is None}
        for r in self.cells:
            if r["ref_id"] is None and not _text(r["name"]) and (r["description"] or r["formula"] or r["notes"]):
                self.notes.append(f"requirements: skipped a measure with answers but no name "
                                  f"({self.dash[r['dashboard_id']]} M{r['slot']})")
        for a in _rows(conn, "SELECT kind, label FROM archive WHERE client_id = ?", cid):
            self.notes.append(f"archive: not converted: {a['kind']} {a['label']!r}")

    def _who(self, person_id, dept_id, note) -> dict:
        return _clean({"person": self.person.get(person_id), "department": self.dept.get(dept_id),
                       "note": _text(note)})

    def _workflow(self, r: dict) -> dict:
        if r["status"] not in INTERVIEW:
            raise ConvertError(f"unknown interview status {r['status']!r}")
        return {"interview": r["status"], "assignee": self.person.get(r["assignee_id"]),
                "followup": bool(r["followup"]), "followup_note": _text(r["followup_note"]),
                "unknown": {k: _text(v) or "" for k, v in json.loads(r["unknown"] or "{}").items() if k != "name"}}

    def _answers(self, kind: str, r: dict) -> dict:
        allowed = requirements.answer_fields(kind)
        a = {}
        for k, v in json.loads(r["answers"] or "{}").items():
            if k not in allowed:
                raise ConvertError(f"{kind} {r['key']}: answer {k!r} is not a {kind} question")
            if k == "systems" and isinstance(v, list):
                v = list(dict.fromkeys(x.strip() for x in v if x.strip()))
            a[k] = _text(v)
        a["owner"] = self._who(r["owner_id"], r["owner_dept_id"], r["owner_note"])
        return a

    def _ordered(self, kind: str, a: dict) -> dict:
        """Answers in question order, empties left out."""
        order = list(requirements.answer_fields(kind))
        return _clean({k: a[k] for k in sorted(a, key=lambda k: order.index(k))})

    def people(self) -> dict:
        return {self.person[p["id"]]: _clean({"name": p["name"].strip(), "role": _text(p["role"]),
                                              "email": _text(p["email"]),
                                              "department": self.dept.get(p["department_id"])})
                for p in self.people_rows}

    def processes(self) -> dict:
        out = {}
        for r in self.process_rows:
            a = self._answers("process", r)
            steps = _rows(self.conn, "SELECT * FROM process_steps WHERE process_id = ? ORDER BY position, id", r["id"])
            a["steps"] = [_clean({"name": s["name"].strip(), "department": self.dept.get(s["dept_id"]),
                                  "person": self.person.get(s["person_id"]), "system": _text(s["system"])})
                          for s in steps if _text(s["name"])]
            out[r["key"]] = _clean({"name": r["name"].strip(), "active": bool(r["active"]), **self._workflow(r),
                                    "answers": self._ordered("process", a), "notes": _text(r["notes"])})
        return out

    def dimensions(self) -> dict:
        return {r["key"]: _clean({"name": r["name"].strip(), **self._workflow(r),
                                  "answers": self._ordered("dimension", self._answers("dimension", r)),
                                  "notes": _text(r["notes"])})
                for r in self.dimension_rows}

    def bus_matrix(self) -> dict:
        out: dict[str, list[str]] = {code: [] for code in self.proc.values()}
        for p, d in self.conn.execute(
                "SELECT b.process_id, b.dimension_id FROM bus_cells b JOIN processes p ON p.id = b.process_id "
                "JOIN dimensions d ON d.id = b.dimension_id WHERE p.client_id = ? ORDER BY p.position, d.position",
                (self.client["id"],)):
            if p in self.proc and d in self.dim:
                out[self.proc[p]].append(self.dim[d])
        return {k: v for k, v in out.items() if v}

    def _shown(self, r: dict) -> str | None:
        """The metric a cell shows: its own, or the one it refers to."""
        return self.metric.get(r["ref_id"] if r["ref_id"] is not None else r["id"])

    def dashboards(self) -> dict:
        out = {}
        for d in self.dashboard_rows:
            entry = {k: _text(d[k]) for k in ("name", "audience", "decisions", "cadence", "access")}
            if d["code"] not in self.proc.values():
                entry["slots"] = {f"M{r['slot']}": self._shown(r) for r in self.cells
                                  if r["dashboard_id"] == d["id"] and self._shown(r)}
            out[d["code"]] = _clean(entry)
        return out

    def process_metric(self) -> list[dict]:
        codes = set(self.proc.values())
        return [{"process_code": self.dash[r["dashboard_id"]], "metric_name": self._shown(r),
                 "slot": f"M{r['slot']}", "display_order": str(r["slot"])}
                for r in self.cells if self.dash[r["dashboard_id"]] in codes and self._shown(r)]

    def measures(self, on_process: dict[str, set[str]]) -> dict:
        """Each measure's answers, by metric name. `on_process`: the process
        dashboards each metric is shown on."""
        out = {}
        for r in self.cells:
            name = self.metric.get(r["id"])
            if not name:
                continue
            unknown = self._workflow(r)
            a = {"formula": _text(r["formula"]),
                 "sources": list(dict.fromkeys(s.strip() for s in json.loads(r["sources"] or "[]") if s.strip())),
                 "source_other": _text(r["source_other"]),
                 "target": _text(r["target"]), "target_none": bool(r["target_none"]),
                 "report": _text(r["report"]), "report_none": bool(r["report_none"]),
                 "breakdowns": _text(r["breakdowns"]), "breakdowns_same": bool(r["breakdowns_same"]),
                 "dimensions": [self.dim[i] for i in json.loads(r["dimension_ids"] or "[]") if i in self.dim],
                 "time": _text(r["time_basis"]),
                 "refresh": _text(r["refresh"]), "refresh_why": _text(r["refresh_why"]),
                 "restatement": _text(r["restatement"]), "restatement_none": bool(r["restatement_none"]),
                 "sme": self._who(r["sme_id"], None, r["sme_note"])}
            process = self.proc.get(r["process_id"])
            if process and on_process.get(name):
                if process not in on_process[name]:
                    self.notes.append(f"measure {name}: its process {process} is not a dashboard it is on "
                                      f"({', '.join(sorted(on_process[name]))}); seeds/process_metric.csv wins")
                process = None
            out[name] = _clean({**unknown, "process": process, "answers": self._ordered("measure", a)})
        return out

    def definitions(self) -> dict:
        """Each measure's definition fields, by metric name, and its backlog fallback."""
        out = {}
        for r in self.cells:
            name = self.metric.get(r["id"])
            if not name:
                continue
            owner = self.role.get(r["owner_id"]) or _text(r["owner_note"]) or requirements.UNOWNED
            if r["owner_id"] is not None and not self.role.get(r["owner_id"]):
                self.notes.append(f"measure {name}: its owner has no role, so it stays {requirements.UNOWNED}")
            out[name] = {"label": r["name"].strip(), "description": _text(r["description"]), "owner": owner,
                         "caveats": [x.strip() for x in (r["notes"] or "").splitlines() if x.strip()],
                         "backlog": (json.loads(r["binding"] or "{}")).get("backlog") or {}}
        return out

    def department_metric(self) -> list[dict]:
        out = []
        for m in _rows(self.conn, "SELECT m.* FROM measure_departments m JOIN requirements r ON r.id = m.requirement_id "
                                  "JOIN dashboards d ON d.id = r.dashboard_id WHERE d.client_id = ? "
                                  "ORDER BY m.position, m.id", self.client["id"]):
            metric = self._shown(self.by_id[m["requirement_id"]])
            if metric and m["department_id"] in self.dept and m["process_id"] in self.proc:
                out.append({"department_code": self.dept[m["department_id"]], "process_code": self.proc[m["process_id"]],
                            "metric_name": metric, "influence": m["influence"]})
            else:
                self.notes.append(f"measure_departments: skipped row {m['id']} (no measure, department or process)")
        return out

    def department_rows(self) -> list[dict]:
        return [{"department_code": self.dept[d["id"]], "department_name": d["name"].strip(),
                 "display_order": str(d["position"] if d["position"] is not None else i)}
                for i, d in enumerate(self.departments, 1)]

    def sketches(self) -> dict:
        out = {}
        for d in self.dashboard_rows:
            tiles = []
            for t in _rows(self.conn, "SELECT * FROM tiles WHERE dashboard_id = ? ORDER BY y, x, id", d["id"]):
                cell = self.by_id.get(t["requirement_id"])
                tiles.append(_clean({"kind": t["kind"], "x": t["x"], "y": t["y"], "w": t["w"], "h": t["h"],
                                     "title": _text(t["title"]), "measure": self._shown(cell) if cell else None,
                                     "dimension": self.dim.get(t["dimension_id"]), "note": _text(t["note"])}))
            if tiles:
                out[d["code"]] = tiles
        return out


# --------------------------------------------------------------- writing --

def _csv(header: list[str], rows: list[dict]) -> str:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(header)
    for r in rows:
        w.writerow([r[h] for h in header])
    return out.getvalue()


def _seed(edit: store.Edit, name: str, header: list[str], rows: list[dict]) -> None:
    """A seed CSV as the workspace has it. Unchanged, it keeps its bytes."""
    current = edit._text(f"seeds/{name}")
    if current is not None and next(csv.reader([current.splitlines()[0]])) != header:
        raise ConvertError(f"seeds/{name} has columns the converter doesn't expect")
    new = _csv(header, rows)
    if current is None or list(csv.DictReader(io.StringIO(current))) != list(csv.DictReader(io.StringIO(new))):
        edit.files[f"seeds/{name}"] = _Text(new)


class _Text:
    def __init__(self, text: str):
        self.text = text

    def render(self) -> str:
        return self.text


#: Files whose order is not display order (a measure shows where its slots put
#: it): entries already there keep their place, new ones go at the end.
UNORDERED = {"measures", "sketches"}
_KIND = {file: kind for kind, file in store.KINDS.items()}


def _merge(node: CommentedMap, value: dict, kind: str, under: str | None = None) -> CommentedMap:
    """`node` changed to hold `value`, key by key, so a value that didn't change
    keeps how it was written (quotes, folding, flow style). `under`: the key
    `node` sits under in its entry, if not the top."""
    order = {None: store.ORDER.get(kind, ()),
             "answers": tuple(requirements.answer_fields(kind)) if kind in requirements.KINDS else ()}.get(under, ())
    for k in [k for k in node if k not in value]:
        node.pop(k)
    for k, v in value.items():
        if isinstance(v, dict) and isinstance(node.get(k), CommentedMap):
            _merge(node[k], v, kind, k)
        elif under == "unknown":
            if node.get(k) != v:
                node[k] = v     # "I don't know" with nobody named is an answer: keep the empty text
        else:
            store._set(node, k, v, order)
    return node


def _entries(edit: store.Edit, name: str, wanted: dict) -> None:
    """requirements/<name>.yml holding exactly `wanted`, in its order. An entry
    already there with the same content keeps its lines and comments."""
    if not wanted and not os.path.exists(edit.pack.path(f"requirements/{name}.yml")):
        return
    f = edit.requirements(name)
    if f.created:
        f.head = [HEADERS[name], "\n"]
        f.created = False
        f.spaced = name != "bus_matrix"     # one line per process
    for key in [k for k in f.keys() if k not in wanted]:
        f.remove(key)
    for i, (key, value) in enumerate(wanted.items()):
        if key in f.keys():
            node = f.node(key)
            f.put(key, _merge(node, value, _KIND[name]) if isinstance(node, CommentedMap) else value)
            if name not in UNORDERED:
                f.move(key, i)
        else:
            f.add(key, value, None if name in UNORDERED else i)


def _project_yml(edit: store.Edit, ws: Workspace, pack: project.Project) -> None:
    """slots and business_systems in project.yml, each line in place or added at the end."""
    rel = "project.yml"
    text = edit._text(rel)
    doc = store._yaml().load(text)
    registry = requirements.load(os.path.join(project.ROOT, "sources", "systems.yml"))
    by_name = {}
    for slug, s in registry.items():
        for label in (slug, s.get("name", ""), s.get("type", "")):
            by_name.setdefault(label.strip().lower(), slug)
    current = dict(doc.get("business_systems") or {})
    systems = CommentedMap()
    for name in json.loads(ws.client["sources"] or "[]"):
        name = name.strip()
        systems[name] = current[name] if name in current else by_name.get(name.lower())
        if systems[name] is None and name not in current:
            ws.notes.append(f"project.yml: business system {name!r} has no architecture system yet (null)")
        elif systems[name] and systems[name] not in pack.systems:
            ws.notes.append(f"project.yml: business system {name!r} is {systems[name]}, which the project "
                            f"doesn't use (systems:)")
    if (ws.client["name"] or "").strip() != pack.name:
        ws.notes.append(f"project.yml: the workspace is called {ws.client['name']!r}; the name is left as it is")
    changed = False
    if doc.get("slots") != ws.client["slots"]:
        doc["slots"] = ws.client["slots"]
        changed = True
    if store._plain(doc.get("business_systems") or {}) != store._plain(systems):
        doc["business_systems"] = systems
        changed = True
    if changed:
        if "slots" not in (text or "") or "business_systems" not in (text or ""):
            note = ("# The requirements: measure slots per dashboard row, and the systems the\n"
                    "# business names in its answers, each with the architecture system it maps to.\n")
            add = {}
            for k in ("slots", "business_systems"):
                if not re.search(rf"^{k}:", text, re.M):
                    add[k] = doc.pop(k)
            body = store._yaml()
            out = io.StringIO()
            body.dump(doc, out)
            extra = io.StringIO()
            body.dump(CommentedMap(add), extra)
            new = out.getvalue().rstrip("\n") + "\n" + note + extra.getvalue()
        else:
            out = io.StringIO()
            store._yaml().dump(doc, out)
            new = out.getvalue()
        edit.files[rel] = _Text(new)


def _define(edit: store.Edit, pack: project.Project, defs: dict, wanted: dict, ws: Workspace) -> None:
    """Each measure's label, description, owner and caveats in its semantic file;
    a measure no semantic file has goes into backlog.yml with the tool's reason."""
    s = store.Store(pack)
    for name, d in wanted.items():
        fields = {k: d[k] for k in store.DEFINITION}
        if name not in defs:
            b = d["backlog"]
            status = b.get("status") or "placeholder"
            entry = {"name": name, "label": d["label"], "status": status, "owner": d["owner"],
                     "description": d["description"], "caveats": d["caveats"],
                     f"{status}_reason": _text(b.get("reason")) or store.NO_FORMULA,
                     "unblock_requires": b.get("unblock_requires") or []}
            edit.entries("backlog.yml", under="metrics").add(name, {k: v for k, v in entry.items()
                                                                     if not store._empty(k, v)})
            ws.notes.append(f"backlog.yml: added {name} ({status}): no semantic file had it")
            continue
        for k in ("description", "caveats"):
            if not fields[k] and defs[name][k]:
                ws.notes.append(f"{defs[name]['file']}: {name} keeps its {k}; the workspace has none")
                fields.pop(k)
        s._define(edit, name, defs[name], fields, [], [])
    for name, d in defs.items():
        if name not in wanted:
            ws.notes.append(f"{d['file']}: {name} is not in the workspace - left as it is")


def convert(conn: sqlite3.Connection, workspace: str, pack: project.Project) -> tuple[dict[str, str], list[str]]:
    """The files the workspace changes in the project, by path relative to it,
    as they should read; and notes on what was skipped or left alone."""
    ws = Workspace(conn, workspace)
    edit = store.Edit(pack)
    _project_yml(edit, ws, pack)
    _seed(edit, "department.csv", ["department_code", "department_name", "display_order"], ws.department_rows())
    pm = ws.process_metric()
    _seed(edit, "process_metric.csv", ["process_code", "metric_name", "slot", "display_order"], pm)
    _seed(edit, "department_metric.csv", ["department_code", "process_code", "metric_name", "influence"],
          ws.department_metric())
    on_process: dict[str, set[str]] = {}
    for r in pm:
        on_process.setdefault(r["metric_name"], set()).add(r["process_code"])
    _define(edit, pack, requirements.definitions(pack), ws.definitions(), ws)
    for name, value in (("people", ws.people()), ("processes", ws.processes()), ("dimensions", ws.dimensions()),
                        ("bus_matrix", ws.bus_matrix()), ("dashboards", ws.dashboards()),
                        ("measures", ws.measures(on_process)), ("sketches", ws.sketches())):
        _entries(edit, name, value)
    texts = edit.changed()
    # The generated files, from the project as the conversion leaves it.
    staged = store.Store(pack)._stage(texts)
    try:
        texts.update(store.Store(pack)._generated(staged))
    finally:
        shutil.rmtree(staged.base, ignore_errors=True)
    return texts, ws.notes


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m core.requirements.convert", description=__doc__.split("\n")[0])
    p.add_argument("db", help="the governance tool's data/requirements.db")
    p.add_argument("--workspace", required=True, help="the workspace's slug, as in /w/<slug>")
    p.add_argument("--project", required=True, help="the project folder under projects/")
    p.add_argument("--check", action="store_true", help="say what would change; write nothing")
    a = p.parse_args()
    pack = project.Project(a.project)
    if not os.path.isdir(pack.root):
        raise SystemExit(f"no project {a.project!r}")
    conn = sqlite3.connect(f"file:{os.path.abspath(a.db)}?mode=ro", uri=True)
    try:
        texts, notes = convert(conn, a.workspace, pack)
    except ConvertError as exc:
        raise SystemExit(f"convert: {exc}") from None
    for n in notes:
        print(f"note: {n}")
    for rel, text in sorted(texts.items()):
        print(f"{'would change' if a.check else 'wrote'}: {rel}")
        if not a.check:
            store._write(pack.path(rel), text)
    if not a.check:
        problems = store.problems(project.Project(a.project))  # project.yml as written
        for prob in problems:
            print(f"problem: {prob}")
        print("convert: ok" if not problems else f"convert: {len(problems)} problem(s)")
    elif not texts:
        print("convert: nothing to change")


if __name__ == "__main__":
    main()
