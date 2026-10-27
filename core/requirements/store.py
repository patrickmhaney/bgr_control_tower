"""The requirements store: the only writer of a project's requirements and definitions.

    from core.requirements.store import Store
    Store(project.current()).patch("measure", "gross_margin", {"owner": "CFO"}, editor="Dana")

The project's files are the store and git is the history: no database. A
save is one small transaction:

  1. take the lock: one save at a time, across threads and processes
  2. refuse if a file it would write has changes nobody committed, so an
     engineer's edit in progress is never saved over
  3. change only the entries the edit names, through their own lines: every
     other line of the file stays byte for byte (ruamel round-trip, so the
     edited entry keeps its comments and order too)
  4. regenerate the files generated from requirements/ (seeds/process.csv and
     the open questions section of docs/open_questions.md)
  5. check the result in a staged copy of the project - the schemas, every
     reference, the semantic lint on the YAML - and refuse on any problem the
     project didn't already have. A refused save writes nothing
  6. write each file to a temp file and swap it in, then commit exactly those
     files on the current branch, the editor as author. If the commit fails,
     put the files back. Nothing is ever pushed

An entry is a top-level key of a requirements file (a process by code, a
measure's answers by metric name, ...) or a metric in the semantic files. A
measure joins the two: its answers in requirements/measures.yml, its
definition - label, description, owner, caveats - in models/semantic/ or
backlog.yml. A metric's name is set from its label when it is added and never
changes; renaming one is an engineering change.

Watcher tells open pages which sections changed, whoever changed the files.
"""
from __future__ import annotations

import csv
import fcntl
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
from contextlib import contextmanager

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.scalarstring import FoldedScalarString, LiteralScalarString

from core import project, requirements

#: Entry kinds, and the requirements file each lives in.
KINDS = {"person": "people", "process": "processes", "dimension": "dimensions", "bus": "bus_matrix",
         "dashboard": "dashboards", "measure": "measures", "sketch": "sketches"}
#: Kinds whose entry is a list, replaced whole: a process's bus matrix row, a dashboard's sketch.
LIST_KINDS = {"bus", "sketch"}
#: Kinds whose entries have questions, and their kind in questions.yml.
QUESTIONED = {"process", "dimension", "measure"}
#: The definition fields of a measure, which live in the semantic files.
DEFINITION = ("label", "description", "owner", "caveats")
#: The order keys are written in when an entry gains one.
ORDER = {
    "person": ("name", "role", "email", "department"),
    "process": ("name", "active", "interview", "assignee", "followup", "followup_note", "unknown", "answers", "notes"),
    "dimension": ("name", "interview", "assignee", "followup", "followup_note", "unknown", "answers", "notes"),
    "measure": ("interview", "assignee", "followup", "followup_note", "unknown", "process", "answers"),
    "dashboard": ("name", "audience", "decisions", "cadence", "access", "slots"),
}
METRIC_ORDER = ("name", "label", "description", "type", "type_params", "filter", "config")
META_ORDER = ("role", "status", "owner", "owner_proposed", "provisional_reason", "caveats", "format",
              "direction", "is_data_quality", "requirement")
BACKLOG_ORDER = ("name", "label", "status", "owner", "owner_proposed", "description", "caveats",
                 "blocked_reason", "placeholder_reason", "unblock_requires")
NO_FORMULA = "Asked for in the requirements; it has no formula yet."
MAX_SLOTS = 12
#: Field labels for commit messages, besides the questions' own.
LABELS = {"name": "Name", "active": "Active", "interview": "Interview status", "assignee": "Assignee",
          "followup": "Follow-up", "followup_note": "Follow-up note", "unknown": "I don't know",
          "notes": "Notes", "process": "Process", "label": "Label", "description": "Definition",
          "owner": "Owner", "caveats": "Caveats", "role": "Role", "email": "Email",
          "department": "Department", "slots": "Slots", "bus": "Bus matrix", "sketch": "Sketch"}
#: The content a save is checked against, copied into the staging folder.
CONTENT = ("project.yml", "backlog.yml", "requirements", "seeds", "models/semantic", "docs/open_questions.md")


class Refused(Exception):
    """A save that was not made, and why, in words for the page."""
    status = 422

    def __init__(self, message: str, problems: list[str] | None = None):
        super().__init__(message)
        self.problems = problems or []


class NotFound(Refused):
    status = 404


class Conflict(Refused):
    status = 409


# ------------------------------------------------------------------- YAML --

def _yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096          # never re-wrap a line that was written by hand
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def _plain(node):
    return json.loads(json.dumps(node, default=str))


def _folded(text: str, width: int = 76) -> FoldedScalarString:
    """Long text as a folded block, broken at spaces near `width`."""
    s = FoldedScalarString(text)
    folds, start = [], 0
    for i, ch in enumerate(s):
        if ch == " " and i - start > width:
            at = s.rfind(" ", start, i)
            at = at if at > start else i
            folds.append(at)
            start = at + 1
    s.fold_pos = folds
    return s


#: Mappings always written as blocks, however small.
BLOCK = {"answers", "slots", "config", "meta"}


def _node(value, old=None, flow: bool = False):
    """A plain value as a ruamel node in the files' style: short lists, and small
    mappings below an entry's top level, in flow style; long text folded."""
    if isinstance(value, str):
        if "\n" in value.strip("\n"):
            return LiteralScalarString(value)
        if isinstance(old, FoldedScalarString) or len(value) > 80:
            if isinstance(old, str) and old.endswith("\n") and not value.endswith("\n"):
                value += "\n"   # keep the file's own chomping
            return _folded(value)
        return value
    if isinstance(value, dict):
        m = CommentedMap()
        for k, v in value.items():
            m[k] = _node(v, flow=k not in BLOCK)
        if flow and _small(value):
            m.fa.set_flow_style()
        return m
    if isinstance(value, list):
        s = CommentedSeq(_node(v) for v in value)
        if all(not isinstance(v, (dict, list)) for v in value):
            s.fa.set_flow_style()
        else:
            for item, v in zip(s, value):
                if isinstance(item, CommentedMap) and _small(v):
                    item.fa.set_flow_style()
        return s
    return value


def _small(value: dict) -> bool:
    return all(not isinstance(v, (dict, list)) and len(str(v)) <= 60 for v in value.values())


def _same(old, new) -> bool:
    if isinstance(old, str) and isinstance(new, str):
        return old.strip() == new.strip()
    return _plain(old) == _plain(new)


def _empty(key: str, value) -> bool:
    """A value the files leave out: nothing, or the default."""
    if key == "active":
        return value is None or value is True
    if key == "interview":
        return value in (None, "", "not_started")
    return value is None or value is False or value == "" or value == [] or value == {}


def _set(m: CommentedMap, key: str, value, order: tuple[str, ...], keep_empty: bool = False) -> None:
    """Set m[key] (or drop it when empty, or None with `keep_empty`), a new key
    going where `order` puts it."""
    if value is None if keep_empty else _empty(key, value):
        m.pop(key, None)
        return
    if key in m:
        if not _same(m[key], value):
            m[key] = value if isinstance(value, CommentedMap) else _node(value, m[key], flow=key not in BLOCK)
        return
    rank = order.index(key) if key in order else len(order)
    pos = next((i for i, k in enumerate(m) if k in order and order.index(k) > rank), len(m))
    m.insert(pos, key, value if isinstance(value, CommentedMap) else _node(value, flow=key not in BLOCK))


class EntryFile:
    """A YAML file of named entries, edited one entry at a time through its own lines.

    Two shapes: a top-level mapping keyed by code (the requirements files), or
    a list of mappings keyed by `name` under one top-level key (the `metrics:`
    of the semantic files and backlog.yml). Each entry owns the lines from its
    key to its last value; comments and blank lines before it travel with it.
    """

    def __init__(self, text: str | None, under: str | None = None):
        self.under = under
        self.created = text is None
        text = text or (f"{under}:\n" if under else "")
        lines = text.splitlines(keepends=True)
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        doc = _yaml().load(text) or CommentedMap()
        if under:
            seq = doc.get(under) or CommentedSeq()
            keys = [item["name"] for item in seq]
            starts = [seq.lc.item(i)[0] for i in range(len(seq))]
            self.indent = seq.lc.item(0)[1] - 2 if len(seq) else 2
            after = [doc.lc.key(k)[0] for k in doc if doc.lc.key(k)[0] > doc.lc.key(under)[0]]
            stop = min(after) if after else len(lines)
        else:
            keys = list(doc)
            starts = [doc.lc.key(k)[0] for k in keys]
            self.indent = 0
            stop = len(lines)
        ends = starts[1:] + [stop]
        self.head = lines[:starts[0]] if starts else lines[:stop]
        self.entries: list[list] = []  # [key, lead lines, body lines]
        prev = starts[0] if starts else stop
        for key, start, end in zip(keys, starts, ends):
            body_end = end
            while body_end - 1 > start and (not lines[body_end - 1].strip()
                                            or lines[body_end - 1].lstrip().startswith("#")):
                body_end -= 1
            self.entries.append([key, lines[prev:start], lines[start:body_end]])
            prev = body_end
        self.tail = lines[prev:] if starts else lines[stop:]
        if under and not keys and self.head and self.head[-1].strip() == f"{under}: []":
            self.head[-1] = f"{under}:\n"
        self.spaced = any(any(not ln.strip() for ln in lead) for _, lead, _ in self.entries[1:]) \
            or len(self.entries) < 2

    def keys(self) -> list[str]:
        return [k for k, _, _ in self.entries]

    def _find(self, key: str) -> list:
        for e in self.entries:
            if e[0] == key:
                return e
        raise KeyError(key)

    def _load(self, body: list[str]):
        text = "".join(ln[self.indent:] if ln.strip() else ln for ln in body)
        doc = _yaml().load(text)
        return doc[0] if self.under else doc[next(iter(doc))]

    def _dump(self, key: str, value) -> list[str]:
        out = io.StringIO()
        if self.under:
            _yaml().dump(CommentedSeq([value]), out)
        else:
            doc = CommentedMap()
            doc[key] = value
            _yaml().dump(doc, out)
        lines = out.getvalue().splitlines(keepends=True)
        if self.under:
            have = len(lines[0]) - len(lines[0].lstrip())
            lines = [" " * self.indent + ln[have:] if ln.strip() else ln for ln in lines]
        return lines

    def get(self, key: str):
        """The entry's value as plain data."""
        return _plain(self._load(self._find(key)[2]))

    def node(self, key: str):
        return self._load(self._find(key)[2])

    def put(self, key: str, value) -> bool:
        """Replace an entry's value with `value` (a ruamel node or plain data). True when it changed."""
        e = self._find(key)
        if _plain(self._load(e[2])) == _plain(value):
            return False
        e[2] = self._dump(key, value if isinstance(value, (CommentedMap, CommentedSeq)) else _node(value))
        return True

    def add(self, key: str, value, position: int | None = None) -> None:
        if key in self.keys():
            raise Refused(f"{key!r} already exists")
        lead = ["\n"] if self.spaced and (self.entries or self.under) else []
        e = [key, lead, self._dump(key, _node(value) if not isinstance(value, CommentedMap) else value)]
        pos = len(self.entries) if position is None else max(0, min(position, len(self.entries)))
        self.entries.insert(pos, e)
        self._respace()

    def remove(self, key: str) -> None:
        self.entries.remove(self._find(key))
        self._respace()

    def move(self, key: str, position: int) -> bool:
        e = self._find(key)
        old = self.entries.index(e)
        position = max(0, min(position, len(self.entries) - 1))
        if old == position:
            return False
        self.entries.remove(e)
        self.entries.insert(position, e)
        self._respace()
        return True

    def _respace(self) -> None:
        """Keep the first entry flush with the head, and the rest spaced as before."""
        for i, e in enumerate(self.entries):
            lead = e[1]
            if i == 0:
                if not self.head or not self.head[-1].strip():
                    while lead and not lead[0].strip():
                        lead.pop(0)
            elif self.spaced and not any(not ln.strip() for ln in lead):
                lead.insert(0, "\n")

    def render(self) -> str:
        head = self.head
        if self.created and not self.under and self.entries:
            head = []
        text = "".join(head) + "".join("".join(lead) + "".join(body) for _, lead, body in self.entries) \
            + "".join(self.tail)
        if self.under and not self.entries:
            text = text.replace(f"{self.under}:\n", f"{self.under}: []\n", 1)
        return text


# -------------------------------------------------------------------- CSV --

class CsvRows:
    """A seed CSV, edited by whole rows: untouched rows keep their bytes."""

    def __init__(self, text: str):
        self.lines = text.splitlines(keepends=True)
        self.header = next(csv.reader([self.lines[0]]))
        self.rows = [dict(zip(self.header, next(csv.reader([ln])))) for ln in self.lines[1:] if ln.strip()]
        self.raw = [ln for ln in self.lines[1:] if ln.strip()]

    def _line(self, row: dict) -> str:
        out = io.StringIO()
        csv.writer(out, lineterminator="\n").writerow([row.get(h, "") for h in self.header])
        return out.getvalue()

    def update(self, match, changes: dict) -> bool:
        """Change the fields of every row `match` accepts. True when one changed."""
        changed = False
        for i, r in enumerate(self.rows):
            new = {**r, **changes}
            if match(r) and new != r:
                self.rows[i], self.raw[i], changed = new, self._line(new), True
        return changed

    def remove(self, match) -> int:
        keep = [(r, ln) for r, ln in zip(self.rows, self.raw) if not match(r)]
        gone = len(self.rows) - len(keep)
        self.rows, self.raw = [r for r, _ in keep], [ln for _, ln in keep]
        return gone

    def insert_after(self, match, row: dict) -> None:
        """Add a row after the last row `match` accepts, or at the end."""
        at = max((i + 1 for i, r in enumerate(self.rows) if match(r)), default=len(self.rows))
        self.rows.insert(at, row)
        self.raw.insert(at, self._line(row))

    def render(self) -> str:
        return self.lines[0] + "".join(self.raw)


# ---------------------------------------------------------------- the save --

class Edit:
    """The files one save changes, loaded on first use and rendered at the end."""

    def __init__(self, pack: project.Project):
        self.pack = pack
        self.before: dict[str, str | None] = {}
        self.files: dict[str, EntryFile | CsvRows] = {}

    def _text(self, rel: str) -> str | None:
        if rel not in self.before:
            path = self.pack.path(rel)
            self.before[rel] = open(path).read() if os.path.exists(path) else None
        return self.before[rel]

    def entries(self, rel: str, under: str | None = None) -> EntryFile:
        if rel not in self.files:
            self.files[rel] = EntryFile(self._text(rel), under)
        return self.files[rel]

    def requirements(self, name: str) -> EntryFile:
        return self.entries(f"requirements/{name}.yml")

    def seed(self, name: str) -> CsvRows:
        rel = f"seeds/{name}"
        if rel not in self.files:
            text = self._text(rel)
            if text is None:
                raise Refused(f"{rel} is missing")
            self.files[rel] = CsvRows(text)
        return self.files[rel]

    def changed(self) -> dict[str, str]:
        out = {}
        for rel, f in self.files.items():
            text = f.render()
            if text != self.before.get(rel):
                out[rel] = text
        return out


def _write(path: str, text: str | None) -> None:
    """Swap a file's content in whole: a reader sees the old file or the new one."""
    if text is None:
        if os.path.exists(path):
            os.remove(path)
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".", suffix=".tmp")
    with os.fdopen(fd, "w") as fh:
        fh.write(text)
    if os.path.exists(path):
        shutil.copymode(path, tmp)
    else:
        os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def problems(pack: project.Project) -> list[str]:
    """Everything a save is checked against: the requirements and the semantic lint on the YAML."""
    from semantic import lint

    out = requirements.check(pack) if os.path.isdir(pack.requirements) else []
    try:
        out += [f"semantic lint: {e}" for e in lint.lint_source(pack)]
    except Exception as exc:  # a semantic file that doesn't parse at all
        out.append(f"semantic lint: {exc.__class__.__name__}: {exc}")
    return out


_THREADS = threading.Lock()


class Store:
    """Reads and saves one project's requirements and definitions."""

    def __init__(self, pack: project.Project):
        self.pack = pack

    # ---------------------------------------------------------------- git
    def _git(self, *args: str, check: bool = True) -> str:
        r = subprocess.run(["git", *args], cwd=self.pack.root, capture_output=True, text=True)
        if check and r.returncode:
            raise Refused(f"git {args[0]} failed: {(r.stderr or r.stdout).strip()}")
        return r.stdout

    @contextmanager
    def _locked(self):
        git_dir = self._git("rev-parse", "--absolute-git-dir", check=False).strip()
        if not git_dir:
            raise Refused("This project is not in a git checkout, so a save has nowhere to be recorded.")
        with _THREADS, open(os.path.join(git_dir, "requirements.lock"), "w") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    @staticmethod
    def _editor(editor: str) -> str:
        editor = " ".join((editor or "").split())
        if not editor:
            raise Refused("Say who's editing: a save is committed in their name.")
        return editor

    def _save(self, editor: str, message, entry: str, change) -> list[str]:
        """Run `change(edit)` as one save: lock, check, write, commit. The files
        written. `message` may be a function, called once the change has run."""
        editor = self._editor(editor)
        with self._locked():
            edit = Edit(self.pack)
            change(edit)
            texts = edit.changed()
            if not texts:
                return []
            message = message() if callable(message) else message
            return self._commit(editor, message, entry, texts)

    def _commit(self, editor: str, message: str, entry: str, texts: dict[str, str | None],
                body: str | None = None) -> list[str]:
        """Check `texts` (None removes a file) with the generated files they
        change, write them and commit them. The lock is held."""
        staged = self._stage(texts)
        try:
            texts.update(self._generated(staged))
            dirty = [ln[3:] for ln in self._git("status", "--porcelain", "--", *texts).splitlines() if ln.strip()]
            if dirty:
                raise Conflict("Someone has changed these files without committing them; commit or "
                               "discard those changes first: " + ", ".join(dirty), dirty)
            before = set(problems(self.pack))
            new = [p for p in problems(staged) if p not in before]
            if new:
                raise Refused("That change was not saved: " + new[0], new)
        finally:
            shutil.rmtree(staged.base, ignore_errors=True)
        old = {rel: (open(self.pack.path(rel)).read() if os.path.exists(self.pack.path(rel)) else None)
               for rel in texts}
        try:
            for rel, text in texts.items():
                _write(self.pack.path(rel), text)
            self._git("add", "--", *texts)
            self._git("commit", "--quiet", f"--author={editor} <>", "-m", message,
                      *(["-m", body] if body else []), "-m", f"Requirements-Entry: {entry}", "--", *texts)
        except Exception:
            for rel, text in old.items():
                _write(self.pack.path(rel), text)
            self._git("reset", "--quiet", "--", *texts, check=False)
            raise
        return sorted(texts)

    def _stage(self, texts: dict[str, str]) -> project.Project:
        """A copy of the project's content in a temp folder, with `texts` written over it."""
        base = tempfile.mkdtemp(prefix="requirements-")
        staged = project.Project(self.pack.slug, base=base)
        for rel in CONTENT:
            src = self.pack.path(rel)
            if os.path.isdir(src):
                shutil.copytree(src, staged.path(rel))
            elif os.path.exists(src):
                os.makedirs(os.path.dirname(staged.path(rel)), exist_ok=True)
                shutil.copyfile(src, staged.path(rel))
        for rel, text in texts.items():
            _write(staged.path(rel), text)
        return staged

    def _generated(self, staged: project.Project) -> dict[str, str]:
        """The generated files that change, written into the stage as well."""
        if not os.path.isdir(staged.requirements):
            return {}
        out = {}
        for rel, text in requirements.generated(staged, requirements.read(staged),
                                                requirements.definitions(staged)).items():
            path = self.pack.path(rel)
            if not os.path.exists(path) or open(path).read() != text:
                out[rel] = text
                _write(staged.path(rel), text)
        return out

    # -------------------------------------------------------------- reads
    def snapshot(self) -> dict:
        """The whole project's requirements, each measure joined with its definition."""
        pack = self.pack
        docs = requirements.read(pack)
        defs = requirements.definitions(pack)
        places = requirements.placements(pack, docs["dashboards"])
        seeds = {name: requirements._seed(pack, f"{name}.csv") for name in ("department", "department_metric")}
        return {
            "project": {"slug": pack.slug, "name": pack.name, "slots": pack.config.get("slots"),
                        "business_systems": pack.config.get("business_systems") or {},
                        "has_requirements": os.path.isdir(pack.requirements)},
            "questions": requirements.questions(),
            "people": docs["people"],
            "departments": seeds["department"],
            "processes": {k: {**v, "answered": requirements.answered("process", v)}
                          for k, v in docs["processes"].items()},
            "dimensions": {k: {**v, "answered": requirements.answered("dimension", v)}
                           for k, v in docs["dimensions"].items()},
            "bus_matrix": docs["bus_matrix"],
            "dashboards": docs["dashboards"],
            "measures": {name: self._measure(docs["measures"].get(name) or {}, d, places, name)
                         for name, d in defs.items()},
            "department_metrics": seeds["department_metric"],
            "sketches": docs["sketches"],
            "problems": requirements.check(pack) if os.path.isdir(pack.requirements) else [],
            "last": self.last(),
        }

    @staticmethod
    def _measure(entry: dict, definition: dict, places: list[dict], name: str) -> dict:
        return {**entry, "definition": definition, "answered": requirements.answered("measure", entry, definition),
                "placements": [p for p in places if p["metric"] == name]}

    def entry(self, kind: str, key: str):
        """One entry as the page shows it."""
        if kind == "measure":
            defs = requirements.definitions(self.pack)
            if key not in defs:
                raise NotFound(f"No measure {key!r}")
            docs = requirements.read(self.pack)
            return self._measure(docs["measures"].get(key) or {}, defs[key],
                                 requirements.placements(self.pack, docs["dashboards"]), key)
        doc = requirements.read(self.pack)[self._file(kind)]
        if key not in doc:
            raise NotFound(f"No {kind} {key!r}")
        value = doc[key]
        if kind in ("process", "dimension"):
            value = {**value, "answered": requirements.answered(kind, value)}
        return value

    def history(self, kind: str, key: str, limit: int = 100) -> list[dict]:
        """The saves that changed one entry, newest first, from git."""
        if kind not in ("department", "project"):
            self._file(kind)
        out = self._git("log", f"-n{limit}", "-E", f"--grep=^Requirements-Entry: {kind}/{re.escape(key)}$",
                        "--format=%H%x1f%an%x1f%aI%x1f%s", check=False)
        return [dict(zip(("commit", "author", "date", "message"), ln.split("\x1f")))
                for ln in out.splitlines() if ln.strip()]

    # ------------------------------------------------------------- writes
    @staticmethod
    def _file(kind: str) -> str:
        if kind not in KINDS:
            raise NotFound(f"No such kind of entry: {kind!r}")
        return KINDS[kind]

    def patch(self, kind: str, key: str, changes: dict | list, editor: str):
        """Change one entry. For a mapping, top-level keys are set (an empty value
        drops one) and `answers` and `unknown` are merged key by key; a list
        entry (a bus matrix row, a sketch) is replaced whole, and an empty one
        removed. A measure's definition fields go to its semantic file."""
        if kind == "department":
            return self._department(key, changes if isinstance(changes, dict) else {}, editor)
        file = self._file(kind)
        fields: list[str] = []
        before_after: list[tuple] = []

        def change(edit: Edit) -> None:
            f = edit.requirements(file)
            if kind in LIST_KINDS:
                if not isinstance(changes, list):
                    raise Refused(f"A {kind} entry is a list")
                old = f.get(key) if key in f.keys() else []
                if not changes:
                    if key in f.keys():
                        f.remove(key)
                elif key in f.keys():
                    f.put(key, changes)
                else:
                    f.add(key, changes)
                if old != _plain(changes):
                    fields.append(kind)
                    before_after.append((kind, ", ".join(map(str, old)) if kind == "bus" else old,
                                         ", ".join(changes) if kind == "bus" else changes))
                return
            if not isinstance(changes, dict):
                raise Refused("Send the fields to change")
            mine = {k: v for k, v in changes.items() if not (kind == "measure" and k in DEFINITION)}
            definition = {k: v for k, v in changes.items() if kind == "measure" and k in DEFINITION}
            if kind == "measure":
                defs = requirements.definitions(self.pack)
                if key not in defs:
                    raise NotFound(f"No measure {key!r}")
                self._define(edit, key, defs[key], definition, fields, before_after)
            elif key not in f.keys():
                raise NotFound(f"No {kind} {key!r}")
            if not mine and kind != "measure":
                return
            node = f.node(key) if key in f.keys() else CommentedMap()
            old = _plain(node)
            order = ORDER.get(kind, ())
            for k, v in mine.items():
                if k in ("answers", "unknown") and isinstance(v, dict):
                    sub = node.get(k) or CommentedMap()
                    sub_order = tuple(requirements.answer_fields(kind)) if k == "answers" else \
                        tuple(requirements.question_keys(kind))
                    # An "I don't know" is kept with no one named; only None takes it away.
                    keep = k == "unknown"
                    for sk, sv in v.items():
                        if k == "answers" and sk not in requirements.answer_fields(kind):
                            raise Refused(f"{sk!r} is not an answer to a {kind} question")
                        gone = sv is None if keep else _empty(sk, sv)
                        if (sk in sub) != (not gone) or (sk in sub and not _same(sub.get(sk), sv)):
                            fields.append(sk if k == "answers" else "unknown")
                            before_after.append((sk if k == "answers" else f"unknown:{sk}", sub.get(sk), sv))
                        _set(sub, sk, sv, sub_order, keep_empty=keep)
                    if k == "unknown" and k not in node and _small(_plain(sub)):
                        sub.fa.set_flow_style()
                    _set(node, k, _plain(sub) if not len(sub) else sub, order)
                else:
                    if not _same(node.get(k), v) and not (k not in node and _empty(k, v)):
                        fields.append(k)
                        before_after.append((k, node.get(k), v))
                    _set(node, k, v, order)
            if kind in QUESTIONED:
                self._interview(edit, kind, key, node, old, fields)
            if key in f.keys():
                if not len(node) and kind == "measure":
                    f.remove(key)
                else:
                    f.put(key, node)
            elif len(node):
                f.add(key, node)

        written = self._save(editor, lambda: _message(kind, key, fields, before_after), f"{kind}/{key}", change)
        return {"entry": changes if kind in LIST_KINDS else self.entry(kind, key), "files": written}

    # -------------------------------------------------------- departments
    def _department(self, code: str, value: dict | None, editor: str, new: bool = False):
        """Add, rename (`value` {"name": ...}) or remove (None) a department in
        seeds/department.csv. A department still used anywhere - a person, an
        owner, a step, another seed - can't be removed; the checks name where."""
        name = " ".join(((value or {}).get("name") or "").split())
        if value is not None and not name:
            raise Refused("A department needs a name")
        if new and not re.fullmatch(r"[A-Z][A-Z0-9_]*", code or ""):
            raise Refused("A department code is capitals, digits and _, e.g. FIN")

        def change(edit: Edit) -> None:
            rows = edit.seed("department.csv")
            here = lambda r: r["department_code"] == code  # noqa: E731
            exists = any(here(r) for r in rows.rows)
            if new:
                if exists:
                    raise Refused(f"There is already a department {code}")
                orders = [int(r["display_order"]) for r in rows.rows if r["display_order"].isdigit()]
                below = [o for o in orders if o < 99]
                rows.insert_after(lambda r: int(r["display_order"] or 0) < 99,
                                  {"department_code": code, "department_name": name,
                                   "display_order": str(max(below, default=0) + 1)})
                return
            if not exists:
                raise NotFound(f"No department {code!r}")
            if value is not None:
                rows.update(here, {"department_name": name})
                return
            for seed in sorted(os.listdir(self.pack.seeds)):
                if seed.endswith(".csv") and seed != "department.csv":
                    used = [r for r in requirements._seed(self.pack, seed) if code in
                            (v for k, v in r.items() if k and "department" in k)]
                    if used:
                        raise Refused(f"{code} is still used in seeds/{seed}: removing it is an engineering change")
            rows.remove(here)

        what = f"Add department {code}" if new else f"Rename department {code} to {name}" if value is not None \
            else f"Remove department {code}"
        written = self._save(editor, what, f"department/{code}", change)
        return written if value is None else {"key": code, "entry": {"department_name": name}, "files": written}

    # ----------------------------------------------------- project settings
    def settings(self, changes: dict, editor: str) -> list[str]:
        """The measure slots per dashboard row (`slots`) and the systems the
        business names (`business_systems`, a list of names; each keeps the
        architecture system it maps to, and a new one maps to none yet), in
        project.yml. A slot still showing a measure can't be taken away, nor a
        system still named in an answer."""
        unknown = set(changes) - {"slots", "business_systems"}
        if unknown:
            raise Refused(f"Not a project setting: {', '.join(sorted(unknown))}")
        what = []

        def change(edit: Edit) -> None:
            f = edit.entries("project.yml")
            if "slots" in changes:
                n = changes["slots"]
                if not isinstance(n, int) or not 1 <= n <= MAX_SLOTS:
                    raise Refused(f"A dashboard has 1 to {MAX_SLOTS} measure slots")
                used = [p for p in requirements.placements(self.pack, requirements.read(self.pack)["dashboards"])
                        if int(p["slot"][1:]) > n]
                if used:
                    raise Refused(f"{used[0]['dashboard']} {used[0]['slot']} still shows {used[0]['metric']}: "
                                  "clear it first")
                f.put("slots", n) if "slots" in f.keys() else f.add("slots", n)
                what.append(f"Measure slots: {n}")
            if "business_systems" in changes:
                names = [" ".join(str(x).split()) for x in changes["business_systems"] or []]
                names = list(dict.fromkeys(x for x in names if x))
                current = self.pack.config.get("business_systems") or {}
                node = f.node("business_systems") if "business_systems" in f.keys() else CommentedMap()
                for gone in [k for k in node if k not in names]:
                    del node[gone]
                for x in names:
                    if x not in node:
                        node[x] = current.get(x)
                if "business_systems" in f.keys():
                    f.put("business_systems", node)
                else:
                    f.add("business_systems", node)
                what.append("Source systems: " + ", ".join(names))

        return self._save(editor, lambda: "; ".join(what), "project/settings", change)

    # ---------------------------------------------------------------- undo
    def last(self) -> dict | None:
        """The newest save to this project, by anyone."""
        out = self._git("log", "-1", "-E", "--grep=^Requirements-Entry: ",
                        "--format=%H%x1f%an%x1f%aI%x1f%s", "--", ".", check=False).strip()
        return dict(zip(("commit", "author", "date", "message"), out.split("\x1f"))) if out else None

    def undo(self, commit: str, editor: str) -> dict:
        """Put back the files one save changed, as a new save - only while it is
        still the newest change to each of them."""
        editor = self._editor(editor)
        with self._locked():
            commit = self._git("rev-parse", "--verify", "--quiet", f"{commit}^{{commit}}", check=False).strip()
            info = self._git("show", "-s", "--format=%s%x1f%B", commit, check=False) if commit else ""
            entry = re.search(r"^Requirements-Entry: (\S+)$", info, re.M)
            if not entry:
                raise NotFound("That isn't a save made here.")
            subject = info.split("\x1f")[0]
            top = self._git("rev-parse", "--show-toplevel").strip()
            files = [p for p in self._git("show", "--format=", "--name-only", commit).splitlines() if p.strip()]
            texts: dict[str, str | None] = {}
            for p in files:
                newest = self._git("log", "-1", "--format=%H", "--", os.path.join(top, p)).strip()
                rel = os.path.relpath(os.path.join(top, p), self.pack.root)
                if newest != commit:
                    raise Conflict(f"{rel} has changed since, so this can't be undone on its own.", [rel])
                r = subprocess.run(["git", "show", f"{commit}^:{p}"], cwd=top, capture_output=True, text=True)
                texts[rel] = r.stdout if r.returncode == 0 else None
            message = subject[len("Undo: "):] if subject.startswith("Undo: ") else f"Undo: {subject}"
            written = self._commit(editor, message, entry.group(1), texts, body=f"This reverts commit {commit}.")
        return {"entry": entry.group(1), "message": message, "files": written}

    def _define(self, edit: Edit, name: str, current: dict, changes: dict, fields: list, before_after: list) -> None:
        """A measure's definition fields, in metrics.yml (meta for owner and caveats) or backlog.yml."""
        if not changes:
            return
        if "owner" in changes and isinstance(changes["owner"], dict):
            person = (requirements.read(self.pack)["people"]).get(changes["owner"].get("person"))
            if not person or not (person.get("role") or "").strip():
                raise Refused("That person has no role to own a definition: give them one in People first")
            changes = {**changes, "owner": person["role"]}
        if "owner" in changes and not (changes["owner"] or "").strip():
            changes = {**changes, "owner": requirements.UNOWNED}
        if "label" in changes and not (changes["label"] or "").strip():
            raise Refused("A measure needs a name")
        backlog = current["file"] == "backlog.yml"
        f = edit.entries(current["file"], under="metrics")
        node = f.node(name)
        meta = node if backlog else node.setdefault("config", CommentedMap()).setdefault("meta", CommentedMap())
        for k, v in changes.items():
            target, order = (node, BACKLOG_ORDER if backlog else METRIC_ORDER) if k in ("label", "description") \
                else (meta, BACKLOG_ORDER if backlog else META_ORDER)
            if not _same(target.get(k), v):
                fields.append(k)
                before_after.append((k, target.get(k), v))
            _set(target, k, v, order)
        f.put(name, node)

    def _interview(self, edit: Edit, kind: str, key: str, node: CommentedMap, old: dict, fields: list) -> None:
        """"Complete" means every question is answered: refuse it otherwise, and
        reopen a complete entry when an answer is taken away. The first answer
        to an entry not started moves it to in progress; assigning or flagging
        it doesn't."""
        if _empty("interview", node.get("interview")) and "interview" not in fields \
                and set(fields) - {"assignee", "followup", "followup_note", "notes", "process", "active"}:
            _set(node, "interview", "in_progress", ORDER[kind])
        entry = _plain(node)
        definition = None
        if kind == "measure":
            definition = dict(requirements.definitions(self.pack)[key])
            f = edit.files.get(definition["file"])
            if f is not None:  # the definition as this save leaves it
                n = f.get(key)
                meta = n if definition["file"] == "backlog.yml" else ((n.get("config") or {}).get("meta") or {})
                definition.update(label=n.get("label") or "", description=(n.get("description") or "").strip(),
                                  owner=meta.get("owner") or "")
        missing = [q["label"] for q in requirements.questions()[kind]
                   if not requirements.answered(kind, entry, definition)[q["key"]]]
        if entry.get("interview") == "complete" and missing:
            if old.get("interview") != "complete":
                raise Refused("Not every question is answered yet: " + ", ".join(missing))
            _set(node, "interview", "in_progress", ORDER[kind])

    def add(self, kind: str, key: str | None, value, editor: str, position: int | None = None,
            dashboard: str | None = None, slot: str | None = None):
        """A new entry. A new measure is named from its label (`value["label"]`),
        starts in backlog.yml with no formula, and can be put in a dashboard slot."""
        if kind == "department":
            return self._department(key, value if isinstance(value, dict) else {}, editor, new=True)
        file = self._file(kind)
        if kind == "measure":
            label = (value or {}).get("label", "").strip() if isinstance(value, dict) else ""
            if not label:
                raise Refused("A measure needs a name")
            key = metric_name(label)
            if key in requirements.definitions(self.pack):
                raise Refused(f"There is already a measure {key!r}")

            def change(edit: Edit) -> None:
                b = edit.entries("backlog.yml", under="metrics")
                b.add(key, {"name": key, "label": label, "status": "placeholder", "owner": requirements.UNOWNED,
                            "placeholder_reason": NO_FORMULA})
                rest = {k: v for k, v in value.items() if k not in ("label",)}
                if rest:
                    edit.requirements(file).add(key, {k: v for k, v in rest.items() if not _empty(k, v)})
                if dashboard:
                    self._place(edit, dashboard, slot, key)
        else:
            if kind == "person" and not key:
                taken = set(requirements.read(self.pack)["people"])
                key = next(f"p{i}" for i in range(1, len(taken) + 2) if f"p{i}" not in taken)
            if not key:
                raise Refused(f"A new {kind} needs a code")

            def change(edit: Edit) -> None:
                f = edit.requirements(file)
                v = value if kind in LIST_KINDS else {k: x for k, x in (value or {}).items() if not _empty(k, x)}
                f.add(key, v, position)

        self._save(editor, f"Add {kind} {key}", f"{kind}/{key}", change)
        return {"key": key, "entry": self.entry(kind, key)}

    def remove(self, kind: str, key: str, editor: str) -> list[str]:
        """Take an entry out. Anything still referring to it refuses the save,
        and says where - except what is only its own: a process's bus matrix
        row, a dashboard's sketch and the measures shown on it (not the
        measures themselves), a backlog measure's answers and slots. A
        measure with a formula is an engineering change, not removed here."""
        if kind == "department":
            return self._department(key, None, editor)
        file = self._file(kind)

        def change(edit: Edit) -> None:
            f = edit.requirements(file)
            if kind == "measure":
                defs = requirements.definitions(self.pack)
                if key not in defs:
                    raise NotFound(f"No measure {key!r}")
                if defs[key]["file"] != "backlog.yml":
                    raise Refused(f"{key} has a formula: removing it is an engineering change")
                edit.entries("backlog.yml", under="metrics").remove(key)
                if key in f.keys():
                    f.remove(key)
                for p in requirements.placements(self.pack, requirements.read(self.pack)["dashboards"]):
                    if p["metric"] == key:
                        self._place(edit, p["dashboard"], p["slot"], None)
                return
            if key not in f.keys():
                raise NotFound(f"No {kind} {key!r}")
            f.remove(key)
            own = {"process": "bus_matrix", "dashboard": "sketches"}.get(kind)
            if own and key in edit.requirements(own).keys():
                edit.requirements(own).remove(key)
            if kind == "dashboard" and os.path.exists(self.pack.path("seeds/process_metric.csv")):
                edit.seed("process_metric.csv").remove(lambda r: r["process_code"] == key)

        return self._save(editor, f"Remove {kind} {key}", f"{kind}/{key}", change)

    def move(self, kind: str, key: str, position: int, editor: str) -> list[str]:
        """Put an entry at `position` (0-based) in its file's order, which is display order."""
        file = self._file(kind)

        def change(edit: Edit) -> None:
            f = edit.requirements(file)
            if key not in f.keys():
                raise NotFound(f"No {kind} {key!r}")
            f.move(key, position)

        return self._save(editor, f"Move {kind} {key} to position {position + 1}", f"{kind}/{key}", change)

    def place(self, dashboard: str, slot: str, metric: str | None, editor: str) -> list[str]:
        """Show a measure in a dashboard slot, or clear the slot (metric None)."""
        what = f"Put {metric} in {dashboard} {slot}" if metric else f"Clear {dashboard} {slot}"
        return self._save(editor, what, f"measure/{metric}" if metric else f"dashboard/{dashboard}",
                          lambda edit: self._place(edit, dashboard, slot, metric))

    def _place(self, edit: Edit, dashboard: str, slot: str | None, metric: str | None) -> None:
        if not slot or not re.fullmatch(r"M[1-9][0-9]*", slot):
            raise Refused("A slot is M1, M2, ...")
        dashboards = edit.requirements("dashboards")
        if dashboard not in dashboards.keys():
            raise NotFound(f"No dashboard {dashboard!r}")
        shown = {p["slot"]: p["metric"] for p in requirements.placements(self.pack, requirements.read(self.pack)["dashboards"])
                 if p["dashboard"] == dashboard}
        if metric is not None and metric in shown.values() and shown.get(slot) != metric:
            raise Refused(f"{dashboard} already shows {metric}: a dashboard shows a measure once")
        if dashboard in requirements.read(self.pack)["processes"]:
            rows = edit.seed("process_metric.csv")
            here = lambda r: r["process_code"] == dashboard and r["slot"] == slot  # noqa: E731
            taken = [r["metric_name"] for r in rows.rows if here(r)]
            if metric is None:
                rows.remove(here)
            elif taken and taken != [metric]:
                raise Refused(f"{dashboard} {slot} already shows {taken[0]}")
            elif not taken:
                rows.insert_after(lambda r: r["process_code"] == dashboard,
                                  {"process_code": dashboard, "metric_name": metric, "slot": slot,
                                   "display_order": slot[1:]})
        else:
            d = dashboards.node(dashboard)
            slots = d.get("slots") or CommentedMap()
            if metric is None:
                slots.pop(slot, None)
            elif slots.get(slot) not in (None, metric):
                raise Refused(f"{dashboard} {slot} already shows {slots[slot]}")
            else:
                slots[slot] = metric
                slots = CommentedMap(sorted(slots.items(), key=lambda kv: int(kv[0][1:])))
            _set(d, "slots", slots if len(slots) else None, ORDER["dashboard"])
            dashboards.put(dashboard, d)
        # A measure taken off a dashboard comes off its sketch's tiles too; the tiles stay.
        gone = shown.get(slot) if metric is None else None
        sketches = edit.requirements("sketches")
        if gone and dashboard in sketches.keys():
            tiles = sketches.get(dashboard)
            if any(t.get("measure") == gone for t in tiles):
                sketches.put(dashboard, [{k: v for k, v in t.items() if not (k == "measure" and v == gone)}
                                         for t in tiles])


def metric_name(label: str) -> str:
    """A metric's name, from the label it is created with. Never changed after."""
    name = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    return name if re.match(r"[a-z]", name) else f"m_{name}"


def _short(value) -> str | None:
    if value is None or value == "" or value is False:
        return "(none)"
    if isinstance(value, (dict, list)):
        return None
    text = " ".join(str(value).split())
    return text if len(text) <= 40 else None


def _message(kind: str, key: str, fields: list[str], before_after: list[tuple]) -> str:
    """`Owner of gross_margin: Finance Manager -> CFO`, or the fields edited."""
    labels = {**LABELS}
    for q in requirements.questions().get(kind, []):
        labels.setdefault(q["key"], q["label"])
        for extra in ("box", "other", "note"):
            if extra in q:
                labels.setdefault(q[extra]["key"], q["label"])
    names = list(dict.fromkeys(labels.get(f, f) for f in fields)) or ["Nothing"]
    if len(before_after) == 1:
        k, old, new = before_after[0]
        if k.startswith("unknown:"):
            q = labels.get(k[len("unknown:"):], k)
            if new is None:
                return f"{q} of {key}: answered, no longer unknown"
            return f"{q} of {key}: I don't know" + (f" (ask {_short(new) or 'someone'})" if new else "")
        a, b = _short(old), _short(new)
        if a is not None and b is not None:
            return f"{labels.get(k, k)} of {key}: {a} -> {b}"
    if kind in LIST_KINDS:
        return f"{names[0]} of {key} edited"
    return f"{', '.join(names)} of {kind} {key} edited"


# ---------------------------------------------------------------- watching --

def _sections(rel: str) -> list[str]:
    """The parts of the page a changed file feeds, by the snapshot's keys."""
    if rel.startswith("requirements/"):
        return [rel[len("requirements/"):-len(".yml")]]
    if rel == "backlog.yml" or rel.startswith("models/semantic/") or rel == "seeds/department_metric.csv":
        return ["measures"]
    if rel == "seeds/process_metric.csv":
        return ["measures", "dashboards"]
    return {"seeds/department.csv": ["departments"], "project.yml": ["project"]}.get(rel, [])


class Watcher:
    """Which sections of a project's requirements changed since the last look,
    by the files' modification times: saves from the Studio and edits made in
    an editor alike. The Studio's event stream polls one per open page."""

    def __init__(self, pack: project.Project):
        self.pack = pack
        self.seen = self._stamps()

    def _files(self) -> list[str]:
        out = ["project.yml", "backlog.yml", "seeds/department.csv", "seeds/process_metric.csv",
               "seeds/department_metric.csv"] + [f"requirements/{n}.yml" for n in requirements.FILES]
        if os.path.isdir(self.pack.semantic_dir):
            out += [f"models/semantic/{f}" for f in sorted(os.listdir(self.pack.semantic_dir)) if f.endswith(".yml")]
        return out

    def _stamps(self) -> dict[str, tuple[int, int]]:
        out = {}
        for rel in self._files():
            try:
                st = os.stat(self.pack.path(rel))
            except FileNotFoundError:
                continue
            out[rel] = (st.st_mtime_ns, st.st_size)
        return out

    def poll(self) -> dict | None:
        """{"files": [...], "sections": [...]} for what changed, or None."""
        now = self._stamps()
        changed = sorted(rel for rel in set(now) | set(self.seen) if now.get(rel) != self.seen.get(rel))
        self.seen = now
        if not changed:
            return None
        return {"files": changed, "sections": sorted({s for rel in changed for s in _sections(rel)})}
