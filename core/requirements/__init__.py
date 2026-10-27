"""The requirements files: what the business asked for, each field in one home.

    projects/<slug>/requirements/
      people.yml      the people named, by id - the only file with names in it
      processes.yml   business processes by code; seeds/process.csv is generated from it
      dimensions.yml  dimensions by code
      bus_matrix.yml  process code -> the dimension codes it is analysed by
      dashboards.yml  the rows of the Measures grid and how each is used
      measures.yml    each measure's discovery answers, by metric name
      sketches.yml    dashboard sketches, by dashboard code

Each file is a mapping keyed by a stable code, in display order, and is
checked by its JSON Schema in schemas/. Every file is optional: a missing one
is empty. A measure's definitions - label, description, owner, caveats - are
not here: they live in the semantic files (models/semantic/, backlog.yml),
the same lines the Governance page shows.

The questions (questions.yml) are one definition: the Studio renders them,
and the `answers` schema of each kind is built from them here, so a question
added there is accepted everywhere at once.

check() is what check-pack runs on a project's requirements/.
"""
from __future__ import annotations

import csv
import io
import json
import os
from functools import cache

import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMAS = os.path.join(HERE, "schemas")
FILES = ("people", "processes", "dimensions", "bus_matrix", "dashboards", "measures", "sketches")
#: The kinds of entry that have questions, and the file each lives in.
KINDS = {"process": "processes", "dimension": "dimensions", "measure": "measures"}
GRID_COLUMNS = 12
UNOWNED = "TBD"


@cache
def questions() -> dict:
    with open(os.path.join(HERE, "questions.yml")) as fh:
        return yaml.safe_load(fh)


def question_keys(kind: str) -> list[str]:
    return [q["key"] for q in questions()[kind]]


# ---------------------------------------------------------------- schemas --

_COMMON = "common.schema.json#/$defs/"


def _fragment(spec: dict) -> dict:
    """The JSON Schema for one answer field, from its question type."""
    kind = spec["type"]
    if kind in ("text", "textarea"):
        return {"$ref": _COMMON + "text"}
    if kind == "choice":
        return {"enum": [c[0] for c in spec["choices"]]}
    if kind == "systems":
        return {"type": "array", "uniqueItems": True, "items": {"type": "string", "minLength": 1}}
    if kind == "steps":
        return {"type": "array", "items": {"$ref": _COMMON + "step"}}
    if kind == "who":
        return {"$ref": _COMMON + "who"}
    if kind == "dimensions":
        return {"type": "array", "uniqueItems": True, "items": {"$ref": _COMMON + "dimension"}}
    raise ValueError(f"questions.yml: unknown question type {kind!r}")


def answer_fields(kind: str) -> dict[str, dict]:
    """Every key an entry's `answers` may hold, with its schema: each question
    whose answer lives here, its tick box, its second field and its note."""
    out = {}
    for q in questions()[kind]:
        if "home" in q:
            continue
        out[q["key"]] = _fragment(q)
        if "box" in q:
            out[q["box"]["key"]] = {"type": "boolean"}
        if "other" in q:
            out[q["other"]["key"]] = _fragment(q["other"])
        if "note" in q:
            out[q["note"]["key"]] = {"$ref": _COMMON + "text"}
    return out


@cache
def _registry() -> Registry:
    resources = []
    for f in sorted(os.listdir(SCHEMAS)):
        with open(os.path.join(SCHEMAS, f)) as fh:
            resources.append((f, Resource.from_contents(json.load(fh))))
    answers = {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "answers.schema.json",
               "$defs": {k: {"type": "object", "additionalProperties": False, "properties": answer_fields(k)}
                         for k in KINDS}}
    resources.append(("answers.schema.json", Resource.from_contents(answers)))
    return Registry().with_resources(resources)


@cache
def _validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(_registry().contents(f"{name}.schema.json"), registry=_registry())


def schema_errors(name: str, doc) -> list[str]:
    """Where `doc`, the content of requirements/<name>.yml, breaks its schema."""
    out = []
    for e in sorted(_validator(name).iter_errors(doc), key=lambda e: [str(p) for p in e.absolute_path]):
        where = ".".join(str(p) for p in e.absolute_path)
        out.append(f"requirements/{name}.yml: {where + ': ' if where else ''}{e.message}")
    return out


# ------------------------------------------------------------------ reading --

def load(path: str) -> dict:
    """A requirements file as plain data; a missing or empty file is {}."""
    if not os.path.exists(path):
        return {}
    with open(path) as fh:
        return yaml.safe_load(fh) or {}


def read(pack) -> dict[str, dict]:
    return {name: load(os.path.join(pack.requirements, f"{name}.yml")) for name in FILES}


def semantic_files(pack) -> list[str]:
    """The files that may hold metric definitions: the semantic models' YAML, then the backlog."""
    folder = pack.semantic_dir
    found = sorted(os.path.join(folder, f) for f in os.listdir(folder) if f.endswith(".yml")) \
        if os.path.isdir(folder) else []
    return found + [pack.backlog]


def definitions(pack) -> dict[str, dict]:
    """Every measure the business can ask about - each KPI and each backlog
    metric - by name, with the definition fields and the file they live in."""
    out = {}
    for path in semantic_files(pack):
        is_backlog = path == pack.backlog
        for m in load(path).get("metrics") or []:
            meta = m if is_backlog else (m.get("config") or {}).get("meta") or {}
            if not is_backlog and meta.get("role") != "kpi":
                continue
            out[m["name"]] = {"file": os.path.relpath(path, pack.root), "label": m.get("label") or "",
                              "description": (m.get("description") or "").strip(),
                              "owner": meta.get("owner") or "", "status": meta.get("status"),
                              "caveats": list(meta.get("caveats") or [])}
    return out


def _seed(pack, name: str) -> list[dict]:
    path = os.path.join(pack.seeds, name)
    if not os.path.exists(path):
        return []
    with open(path) as fh:
        return list(csv.DictReader(fh))


def placements(pack, dashboards: dict) -> list[dict]:
    """Every measure on every dashboard: process dashboards from
    seeds/process_metric.csv, the others from dashboards.yml."""
    out = [{"dashboard": r["process_code"], "slot": r["slot"], "metric": r["metric_name"]}
           for r in _seed(pack, "process_metric.csv")]
    for code, d in dashboards.items():
        for slot, metric in ((d or {}).get("slots") or {}).items():
            out.append({"dashboard": code, "slot": slot, "metric": metric})
    return out


def answered(kind: str, entry: dict, definition: dict | None = None) -> dict[str, bool]:
    """Which questions have an answer, in question order. "I don't know" counts:
    the point is to find the gaps, not to block on them. A measure's name,
    definition and owner are read from its definition in the semantic files."""
    a, unknown = entry.get("answers") or {}, entry.get("unknown") or {}
    home = {"name": entry.get("name"), **{k: (definition or {}).get(k) for k in ("label", "description", "owner")}}

    def has(v) -> bool:
        return bool(v.strip()) if isinstance(v, str) else bool(v)

    out = {}
    for q in questions()[kind]:
        k = q["key"]
        if "home" in q:
            v = home[q["home"]]
            ok = has(v) and not (q["home"] == "owner" and v == UNOWNED)
        elif q["type"] == "steps":
            ok = any(has(s.get("name")) for s in a.get("steps") or [])
        else:
            ok = has(a.get(k)) or ("box" in q and a.get(q["box"]["key"]) is True) \
                or ("other" in q and has(a.get(q["other"]["key"])))
        out[k] = ok or (k in unknown and q.get("unknown", True))
    return out


# ------------------------------------------------------- generated files --

def process_csv(processes: dict) -> str:
    """seeds/process.csv, generated from processes.yml: file order is display order."""
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["process_code", "display_order", "is_active"])
    for i, (code, p) in enumerate(processes.items(), 1):
        w.writerow([code, i, int(p.get("active", True))])
    return out.getvalue()


OPEN_START = "<!-- requirements:start - generated from requirements/ on every save; edit the answers, not this section -->"
OPEN_END = "<!-- requirements:end -->"


def _cell(text) -> str:
    return " ".join(str(text).split()).replace("|", "\\|") or "-"


def open_questions(docs: dict[str, dict], defs: dict[str, dict]) -> str:
    """The section of docs/open_questions.md the requirements own: every question
    answered "I don't know", and every follow-up, markers included."""
    unknown, followups = [], []
    labels = {kind: {q["key"]: q["label"] for q in questions()[kind]} for kind in KINDS}
    for kind, file in KINDS.items():
        for key, e in docs[file].items():
            name = (defs.get(key) or {}).get("label") if kind == "measure" else e.get("name")
            item = f"{kind.capitalize()} {name or key}" + (f" (`{key}`)" if name and name != key else "")
            for q, who in (e.get("unknown") or {}).items():
                unknown.append(f"| {_cell(item)} | {_cell(labels[kind].get(q, q))} | {_cell(who)} |")
            if e.get("followup"):
                followups.append(f"| {_cell(item)} | {_cell(e.get('followup_note', ''))} |")
    lines = [OPEN_START, "", "## Asked in the requirements", ""]
    lines += ["Answered \"I don't know\" in the Requirements tab, with who might know.", ""]
    lines += ["| Item | Question | Who might know |", "|---|---|---|", *unknown] if unknown else ["None."]
    lines += ["", "Flagged for follow-up.", ""]
    lines += ["| Item | Note |", "|---|---|", *followups] if followups else ["None."]
    return "\n".join(lines + ["", OPEN_END]) + "\n"


def with_open_questions(text: str | None, section: str) -> str:
    """docs/open_questions.md with its generated section replaced, or appended
    when it has none yet. Everything else in the file is left as written."""
    text = text or "# Open questions\n"
    if OPEN_START in text and OPEN_END in text:
        head, rest = text.split(OPEN_START, 1)
        tail = rest.split(OPEN_END, 1)[1].lstrip("\n")
        return head + section + (("\n" + tail) if tail else "")
    return text.rstrip("\n") + "\n\n" + section


# ----------------------------------------------------------------- checks --

def check(pack) -> list[str]:
    """Each file against its schema, then every reference between files, then
    the files generated from them. Empty when the requirements are sound."""
    folder = pack.requirements
    problems = [f"requirements/{f}: not a requirements file (expected one of: "
                f"{', '.join(n + '.yml' for n in FILES)})"
                for f in sorted(os.listdir(folder)) if not f.endswith(".yml") or f[:-4] not in FILES
                if f != ".DS_Store"]
    docs: dict[str, dict] = {}
    for name in FILES:
        try:
            doc = load(os.path.join(folder, f"{name}.yml"))
        except yaml.YAMLError as exc:
            problems.append(f"requirements/{name}.yml: not valid YAML ({exc.__class__.__name__})")
            continue
        errors = schema_errors(name, doc)
        problems += errors
        if not errors:
            docs[name] = doc
    if len(docs) < len(FILES):
        return problems  # references are only checked between sound files
    return problems + references(pack, docs)


def references(pack, docs: dict[str, dict]) -> list[str]:
    """Every code, id and name one file uses exists where it is defined."""
    people, procs, dims = docs["people"], docs["processes"], docs["dimensions"]
    dashboards, measures = docs["dashboards"], docs["measures"]
    departments = {r["department_code"] for r in _seed(pack, "department.csv")}
    systems = set(pack.config.get("business_systems") or {})
    defs = definitions(pack)
    problems: list[str] = []

    def need(where: str, kind: str, value, known) -> None:
        if value is not None and value not in known:
            problems.append(f"{where}: unknown {kind} {value!r}")

    def who(where: str, w: dict | None) -> None:
        if w:
            need(where, "person", w.get("person"), people)
            need(where, "department", w.get("department"), departments)

    def entry(where: str, kind: str, e: dict) -> None:
        a = e.get("answers") or {}
        need(where + ".assignee", "person", e.get("assignee"), people)
        for k in e.get("unknown") or {}:
            if k == "name" or k not in question_keys(kind):
                problems.append(f"{where}.unknown: {k!r} is not a question that can be unknown")
        for q in questions()[kind]:
            if q["type"] == "systems":
                for s in a.get(q["key"]) or []:
                    need(f"{where}.answers.{q['key']}", "system (project.yml business_systems)", s, systems)
            elif q["type"] == "who" and "home" not in q:
                who(f"{where}.answers.{q['key']}", a.get(q["key"]))
            elif q["type"] == "steps":
                for i, s in enumerate(a.get(q["key"]) or []):
                    at = f"{where}.answers.steps.{i}"
                    who(at, s)
                    if s.get("system"):
                        need(at, "system (project.yml business_systems)", s["system"], systems)
        for d in a.get("dimensions") or []:
            need(where + ".answers.dimensions", "dimension", d, dims)

    for pid, p in people.items():
        need(f"requirements/people.yml: {pid}", "department", p.get("department"), departments)
    for code, p in procs.items():
        entry(f"requirements/processes.yml: {code}", "process", p)
    for code, d in dims.items():
        entry(f"requirements/dimensions.yml: {code}", "dimension", d)
    for code, ticks in docs["bus_matrix"].items():
        need("requirements/bus_matrix.yml", "process", code, procs)
        for d in ticks:
            need(f"requirements/bus_matrix.yml: {code}", "dimension", d, dims)

    slots = pack.config.get("slots")
    for code, d in dashboards.items():
        where = f"requirements/dashboards.yml: {code}"
        if (d or {}).get("slots") and code in procs:
            problems.append(f"{where}: a process dashboard's measures are in seeds/process_metric.csv, not slots")
        for slot, metric in ((d or {}).get("slots") or {}).items():
            need(f"{where}.slots.{slot}", "measure (a KPI or backlog metric)", metric, defs)
            if slots and int(slot[1:]) > slots:
                problems.append(f"{where}.slots.{slot}: project.yml allows {slots} slots per dashboard")
    on = {}
    for pl in placements(pack, dashboards):
        on.setdefault(pl["dashboard"], set()).add(pl["metric"])
    for name, m in measures.items():
        where = f"requirements/measures.yml: {name}"
        need(where, "measure (a KPI or backlog metric)", name, defs)
        need(where + ".process", "process", m.get("process"), procs)
        entry(where, "measure", m)
    for code, tiles in docs["sketches"].items():
        where = f"requirements/sketches.yml: {code}"
        need(where, "dashboard", code, dashboards)
        for i, t in enumerate(tiles):
            if t["x"] + t["w"] > GRID_COLUMNS:
                problems.append(f"{where}.{i}: a tile must fit in {GRID_COLUMNS} columns")
            if t.get("measure") and t["measure"] not in on.get(code, set()):
                problems.append(f"{where}.{i}: {t['measure']!r} is not on this dashboard")
            need(f"{where}.{i}", "dimension", t.get("dimension"), dims)

    if os.path.exists(os.path.join(pack.requirements, "processes.yml")):
        for seed in ("process_metric.csv", "department_metric.csv"):
            for r in _seed(pack, seed):
                need(f"seeds/{seed}", "process (requirements/processes.yml)", r["process_code"], procs)
    if os.path.exists(os.path.join(pack.requirements, "dashboards.yml")):
        for r in _seed(pack, "process_metric.csv"):
            need("seeds/process_metric.csv", "dashboard (requirements/dashboards.yml)", r["process_code"], dashboards)
    return problems + generated_problems(pack, docs, defs)


def generated(pack, docs: dict[str, dict], defs: dict[str, dict]) -> dict[str, str]:
    """The files generated from the requirements, by path relative to the
    project, as they should read now."""
    out = {}
    if os.path.exists(os.path.join(pack.requirements, "processes.yml")):
        out["seeds/process.csv"] = process_csv(docs["processes"])
    path = os.path.join(pack.docs, "open_questions.md")
    current = open(path).read() if os.path.exists(path) else None
    out["docs/open_questions.md"] = with_open_questions(current, open_questions(docs, defs))
    return out


def regenerate(pack) -> list[str]:
    """Rewrite the generated files that are out of date; the paths rewritten."""
    out = []
    for rel, text in generated(pack, read(pack), definitions(pack)).items():
        path = pack.path(rel)
        if not os.path.exists(path) or open(path).read() != text:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as fh:
                fh.write(text)
            out.append(rel)
    return out


def generated_problems(pack, docs: dict[str, dict], defs: dict[str, dict]) -> list[str]:
    problems = []
    for rel, text in generated(pack, docs, defs).items():
        path = pack.path(rel)
        if not os.path.exists(path) or open(path).read() != text:
            problems.append(f"{rel}: out of date with requirements/ (generated: the Studio rewrites it "
                            f"on every save; `python -m ctl requirements --regenerate` does it by hand)")
    return problems
