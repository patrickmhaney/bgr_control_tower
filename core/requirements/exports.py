"""The requirements as documents to hand round: generated from the files, never stored.

    handbook.md     everything, in the order the work is done: processes, the bus
                    matrix, dimensions, measures, dashboards and ownership
    catalogue.md    the measures by dashboard, each with its answers and metric status
    measures.csv    one row per measure, one column per question
    bus-matrix.csv  processes down the side, dimensions across the top

Every answer is written the way questions.yml asks it, so a question added
there shows up here too. The engineering catalogue - formulas, cubes,
dimensions - is semantic.catalog's docs/metric_catalog.md; these are the
business's side of the same measures.
"""
from __future__ import annotations

import csv
import datetime as dt
import io

from core import requirements as rq

FILES = {"handbook.md": "text/markdown", "catalogue.md": "text/markdown",
         "measures.csv": "text/csv", "bus-matrix.csv": "text/csv"}
TILES = {"kpi": "Headline number", "line": "Trend", "bar": "Comparison", "table": "Table",
         "filter": "Filter", "text": "Note"}
#: The warehouse term beside the business's answer, for whoever builds it.
HISTORY = {"as_was": "keep history (type 2)", "as_is": "overwrite (type 1)", "both": "keep history, show either"}


class Project:
    """One project's requirements, read once, with the lookups every document needs."""

    def __init__(self, pack):
        self.pack = pack
        self.docs = rq.read(pack)
        self.defs = rq.definitions(pack)
        self.people, self.procs, self.dims = self.docs["people"], self.docs["processes"], self.docs["dimensions"]
        self.dashboards, self.answers = self.docs["dashboards"], self.docs["measures"]
        self.departments = {r["department_code"]: r["department_name"] for r in rq._seed(pack, "department.csv")}
        self.places = rq.placements(pack, self.dashboards)
        self.status = dict(rq.questions()["interview"])
        order = list(self.dashboards)
        self.places.sort(key=lambda p: (order.index(p["dashboard"]) if p["dashboard"] in order else len(order),
                                        int(p["slot"][1:])))

    # ---------------------------------------------------------------- words
    def name(self, kind: str, key: str) -> str:
        if kind == "measure":
            return (self.defs.get(key) or {}).get("label") or key
        return ({"process": self.procs, "dimension": self.dims}[kind].get(key) or {}).get("name") or key

    def who(self, w: dict | None) -> str:
        if not w:
            return ""
        if w.get("person"):
            p = self.people.get(w["person"]) or {}
            return p.get("name", w["person"]) + (f" ({p['role']})" if p.get("role") else "")
        if w.get("department"):
            return self.departments.get(w["department"], w["department"])
        return w.get("note") or ""

    def owner(self, role: str) -> str:
        """A measure's owner: the role its definition records, and who holds it."""
        if not role or role == rq.UNOWNED:
            return ""
        names = [p["name"] for p in self.people.values() if p.get("role") == role]
        return role + (f" ({', '.join(names)})" if names else "")

    def answer(self, kind: str, q: dict, e: dict, definition: dict | None = None) -> str:
        """One answer as text, the way the question puts it."""
        a = e.get("answers") or {}
        if "home" in q:
            if q["home"] == "owner":
                return self.owner((definition or {}).get("owner", ""))
            return (e.get("name") if q["home"] == "name" else (definition or {}).get(q["home"])) or ""
        if q["type"] == "steps":
            return f"{len([s for s in a.get('steps') or [] if (s.get('name') or '').strip()])} steps"
        if q["type"] == "who":
            text = self.who(a.get(q["key"]))
        elif q["type"] == "choice":
            text = next((c[1] for c in q["choices"] if c[0] == a.get(q["key"])), "")
            if q["key"] == "history" and a.get("history"):
                text += f": {HISTORY[a['history']]}"
        elif q["type"] == "systems":
            text = "; ".join(a.get(q["key"]) or [])
        else:
            text = " ".join(str(a.get(q["key"]) or "").split())
        if "box" in q and a.get(q["box"]["key"]) and not text:
            text = q["box"]["label"]
        if "other" in q and a.get(q["other"]["key"]):
            other = a[q["other"]["key"]]
            other = ", ".join(self.name("dimension", d) for d in other) if isinstance(other, list) else str(other)
            text = "; ".join(x for x in (text, other) if x)
        if "note" in q and a.get(q["note"]["key"]):
            text += f" ({' '.join(a[q['note']['key']].split())})"
        return text

    def unknown(self, kind: str, e: dict) -> str:
        """The questions answered "I don't know", with who might know."""
        labels = {q["key"]: q["label"] for q in rq.questions()[kind]}
        return "; ".join(labels.get(k, k) + (f" (ask {who})" if who else "")
                         for k, who in sorted((e.get("unknown") or {}).items(),
                                              key=lambda kv: list(labels).index(kv[0]) if kv[0] in labels else 99))

    def state(self, e: dict) -> str:
        return self.status[e.get("interview") or "not_started"] + (" (needs follow-up)" if e.get("followup") else "")

    def where(self, name: str) -> list[str]:
        return [f"{p['dashboard']} {p['slot']}" for p in self.places if p["metric"] == name]

    def ordered(self) -> list[str]:
        """Every measure, in dashboard order, then those on no dashboard."""
        seen = list(dict.fromkeys(p["metric"] for p in self.places if p["metric"] in self.defs))
        return seen + [n for n in self.defs if n not in seen]

    def process_of(self, name: str) -> str | None:
        p = next((x["dashboard"] for x in self.places if x["metric"] == name and x["dashboard"] in self.procs), None)
        return p or (self.answers.get(name) or {}).get("process")


def _cell(v) -> str:
    return " ".join(str(v).split()).replace("|", "/")


def _table(fields) -> list[str]:
    rows = [f"| {k} | {_cell(v)} |" for k, v in fields if v]
    return ["| | |", "|---|---|", *rows] if rows else []


def _today() -> str:
    return dt.date.today().isoformat()


# ----------------------------------------------------------------- measures --

def _measure(P: Project, name: str, depth: int) -> list[str]:
    d, e = P.defs[name], P.answers.get(name) or {}
    out = ["#" * depth + f" {d['label'] or name}", ""]
    if d["description"]:
        out += [d["description"], ""]
    built = "no formula yet (backlog)" if d["file"] == "backlog.yml" else f"formula in {d['file']}"
    fields = [("Metric", f"`{name}`: {d['status']}, {built}"), ("Interview", P.state(e)),
              ("On dashboards", ", ".join(P.where(name))),
              ("Business process", P.name("process", P.process_of(name)) if P.process_of(name) else "")]
    fields += [(q["label"], P.answer("measure", q, e, d)) for q in rq.questions()["measure"]
               if q.get("home") not in ("label", "description")]
    fields += [("Why no number yet", d["reason"] if d["file"] == "backlog.yml" else ""),
               ("Caveats", "; ".join(d["caveats"])), ("Don't know yet", P.unknown("measure", e))]
    out += _table(fields)
    if e.get("followup") and e.get("followup_note"):
        out += ["", f"> Open question: {_cell(e['followup_note'])}"]
    return out + [""]


def _measure_sections(P: Project, depth: int) -> list[str]:
    """Measures by dashboard: each written out on the first dashboard that shows
    it, and named on the others."""
    out, written = [], set()
    for code, dash in P.dashboards.items():
        names = [p["metric"] for p in P.places if p["dashboard"] == code and p["metric"] in P.defs]
        if not names:
            continue
        out += ["#" * depth + f" {code}" + (f": {dash['name']}" if (dash or {}).get("name") else ""), ""]
        also = []
        for n in names:
            if n in written:
                also.append(n)
                continue
            written.add(n)
            out += _measure(P, n, depth + 1)
        if also:
            first = {n: next(p["dashboard"] for p in P.places if p["metric"] == n) for n in also}
            out += ["Also shows " + ", ".join(f"{P.name('measure', n)} (on {first[n]})" for n in also) + ".", ""]
    rest = [n for n in P.defs if n not in written]
    if rest:
        out += ["#" * depth + " Not on a dashboard", ""]
        for n in rest:
            out += _measure(P, n, depth + 1)
    return out


def catalogue_md(pack) -> str:
    """The measure catalogue in Markdown: pastes into Confluence, SharePoint, Notion or a wiki."""
    P = Project(pack)
    return "\n".join([f"# {pack.name}: measure catalogue", "",
                      f"{len(P.defs)} measures. Generated {_today()} from the project's requirements/ and semantic files.",
                      "", *_measure_sections(P, 2)])


def measures_csv(pack) -> str:
    P = Project(pack)
    qs = [q for q in rq.questions()["measure"] if q["key"] != "name"]
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["metric", "measure", "dashboards", "metric_status", "built", "interview", "business_process",
                *[q["label"].lower().replace(" ", "_") for q in qs], "caveats", "dont_know", "assignee",
                "follow_up", "follow_up_note"])
    for n in P.ordered():
        d, e = P.defs[n], P.answers.get(n) or {}
        w.writerow([n, d["label"], "; ".join(P.where(n)), d["status"], "no" if d["file"] == "backlog.yml" else "yes",
                    P.status[e.get("interview") or "not_started"], P.process_of(n) or "",
                    *[P.answer("measure", q, e, d) for q in qs], "; ".join(d["caveats"]), P.unknown("measure", e),
                    P.who({"person": e["assignee"]}) if e.get("assignee") else "",
                    "yes" if e.get("followup") else "", e.get("followup_note") or ""])
    return buf.getvalue()


def bus_csv(pack) -> str:
    P = Project(pack)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["business_process", "records", *[d.get("name") or k for k, d in P.dims.items()]])
    for code, p in P.procs.items():
        ticks = P.docs["bus_matrix"].get(code) or []
        w.writerow([p.get("name") or code, " ".join(str((p.get("answers") or {}).get("event") or "").split()),
                    *["x" if d in ticks else "" for d in P.dims]])
    return buf.getvalue()


# ----------------------------------------------------------------- handbook --

def _entries(P: Project, kind: str, lead: str) -> list[str]:
    out = []
    for code, e in (P.procs if kind == "process" else P.dims).items():
        a = e.get("answers") or {}
        out += [f"### {e.get('name') or code}", ""]
        if a.get(lead):
            out += [" ".join(a[lead].split()), ""]
        fields = [("Status", P.state(e))]
        if kind == "dimension":
            fields.append(("Used by", ", ".join(P.name("process", p) for p, ds in P.docs["bus_matrix"].items() if code in ds)))
        fields += [(q["label"], P.answer(kind, q, e) or ("Not yet named" if q["type"] == "who" else ""))
                   for q in rq.questions()[kind] if q["key"] not in ("name", lead, "steps")]
        fields.append(("Don't know yet", P.unknown(kind, e)))
        out += _table(fields)
        steps = [s for s in a.get("steps") or [] if (s.get("name") or "").strip()]
        if steps:
            out += ["", "| Step | Who | System |", "|---|---|---|"]
            out += [f"| {i}. {_cell(s['name'])} | {_cell(P.who(s))} | {_cell(s.get('system', ''))} |"
                    for i, s in enumerate(steps, 1)]
        if e.get("notes"):
            out += ["", f"> Notes: {_cell(e['notes'])}"]
        out.append("")
    return out


def _dashboards(P: Project) -> list[str]:
    out = []
    bus = P.docs["bus_matrix"]
    for code, dash in P.dashboards.items():
        dash = dash or {}
        tiles = sorted(P.docs["sketches"].get(code) or [], key=lambda t: (t["y"], t["x"]))
        names = list(dict.fromkeys(p["metric"] for p in P.places if p["dashboard"] == code))
        if not tiles and not names and not any(dash.get(k) for k in ("audience", "decisions", "cadence", "access")):
            continue
        procs = list(dict.fromkeys(p for p in (P.process_of(n) for n in names) if p in P.procs))
        n_ticked = {d: sum(d in (bus.get(p) or []) for p in procs) for d in P.dims}
        out += [f"### {code}" + (f": {dash['name']}" if dash.get("name") else ""), ""]
        out += _table([*[(q["label"], dash.get(q["key"], "")) for q in rq.questions()["dashboard"]],
                       ("Measures", ", ".join(P.name("measure", n) for n in names)),
                       ("Processes", ", ".join(P.name("process", p) for p in procs)),
                       ("Filters for the whole dashboard",
                        ", ".join(P.name("dimension", d) for d, n in n_ticked.items() if procs and n == len(procs))),
                       ("Filters for some measures only",
                        ", ".join(P.name("dimension", d) for d, n in n_ticked.items() if 0 < n < len(procs)))])
        if tiles:
            out += ["", "| Tile | Shows | By | Note |", "|---|---|---|---|"]
            out += [f"| {TILES.get(t['kind'], t['kind'])}{': ' + _cell(t['title']) if t.get('title') else ''} "
                    f"| {_cell(P.name('measure', t['measure']) if t.get('measure') else '')} "
                    f"| {_cell(P.name('dimension', t['dimension']) if t.get('dimension') else '')} "
                    f"| {_cell(t.get('note', ''))} |" for t in tiles]
        out.append("")
    return out


def _ownership(P: Project) -> list[str]:
    def dept(kind: str, key: str):
        """The owning department; "none" for an owner without one; None when nobody owns it."""
        if kind == "measure":
            role = P.defs[key]["owner"]
            if not role or role == rq.UNOWNED:
                return None
            holders = [p.get("department") for p in P.people.values() if p.get("role") == role]
            return next((d for d in holders if d), "none")
        w = ((P.procs if kind == "process" else P.dims)[key].get("answers") or {}).get("owner")
        if not w:
            return None
        if w.get("department"):
            return w["department"]
        return (P.people.get(w.get("person")) or {}).get("department") or "none"

    groups = (("process", list(P.procs)), ("dimension", list(P.dims)), ("measure", list(P.defs)))
    out = ["| Department | Processes owned | Dimensions owned | Measures owned |", "|---|---|---|---|"]
    rows = [*sorted(P.departments.items(), key=lambda kv: kv[1].lower()), ("none", "No department"),
            (None, "Not owned yet")]
    for code, name in rows:
        cells = [", ".join(P.name(kind, k) for k in keys if dept(kind, k) == code) for kind, keys in groups]
        if any(cells):
            out.append(f"| {_cell(name)} | " + " | ".join(_cell(c) for c in cells) + " |")
    return out + [""]


def handbook_md(pack) -> str:
    """Everything in one Markdown document, in the order the work is done."""
    P = Project(pack)
    bus = P.docs["bus_matrix"]
    out = [f"# {pack.name}: data warehouse requirements", "",
           f"{len(P.procs)} business processes, {len(P.dims)} dimensions, {len(P.defs)} measures. "
           f"Generated {_today()} from the project's requirements/ and semantic files.", ""]
    out += ["## Business processes", "", *_entries(P, "process", "purpose")]
    out += ["## Bus matrix", "", "Business processes down the side, the dimensions they're analysed by across the top.", ""]
    if P.procs and P.dims:
        out += ["| Process | " + " | ".join(_cell(P.name("dimension", d)) for d in P.dims) + " |",
                "|---|" + "---|" * len(P.dims)]
        out += [f"| {_cell(P.name('process', p))} | " + " | ".join("✓" if d in (bus.get(p) or []) else "" for d in P.dims)
                + " |" for p in P.procs]
        out.append("")
    out += ["## Dimensions", "", *_entries(P, "dimension", "definition")]
    out += ["## Measures", "", *_measure_sections(P, 3)]
    out += ["## Dashboards", "", "The processes each dashboard's measures come from. A filter on a dimension "
            "every one of those processes is analysed by works across the whole dashboard.", "", *_dashboards(P)]
    out += ["## Ownership", "", *_ownership(P)]
    return "\n".join(out)


def render(pack, name: str) -> str:
    return {"handbook.md": handbook_md, "catalogue.md": catalogue_md, "measures.csv": measures_csv,
            "bus-matrix.csv": bus_csv}[name](pack)
