"""The requirements files (core/requirements) and the store that saves them.

The format: the question sets, the schemas and every reference check. The
store, on a copy of projects/sample in its own git repository: an edit changes
only its own lines, a save the lint refuses writes nothing, concurrent saves
both land, and each save is one commit in the editor's name.
"""
import shutil
import subprocess
import threading

import pytest
import yaml
from fastapi.testclient import TestClient

from core import pack, project, requirements
from core.requirements.store import Conflict, Refused, Store, Watcher


def test_question_sets():
    q = requirements.questions()
    assert (len(q["process"]), len(q["dimension"]), len(q["measure"])) == (11, 9, 12)
    # A measure's name, definition and owner live in the semantic files, not in its answers.
    assert not {"name", "definition", "owner"} & set(requirements.answer_fields("measure"))
    assert {"target_none", "source_other", "dimensions", "refresh_why"} <= set(requirements.answer_fields("measure"))


def test_the_sample_requirements_pass():
    sample = project.Project("sample")
    assert requirements.check(sample) == []
    defs = requirements.definitions(sample)
    measures = requirements.read(sample)["measures"]
    assert set(measures) <= set(defs)
    assert all(requirements.answered("measure", measures["on_time_delivery_rate"],
                                     defs["on_time_delivery_rate"]).values())


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """projects/sample copied into a scratch git repository, and in use."""
    root = tmp_path / "projects" / "sample"
    shutil.copytree(project.Project("sample").root, root,
                    ignore=shutil.ignore_patterns("target", "dbt_packages", "logs"))
    for cmd in (["init", "-q"], ["config", "user.name", "Studio"], ["config", "user.email", "studio@example.com"],
                ["add", "-A"], ["commit", "-qm", "start"]):
        subprocess.run(["git", *cmd], cwd=tmp_path, check=True)
    monkeypatch.setattr(project, "PROJECTS", str(tmp_path / "projects"))
    monkeypatch.setattr(project, "_active", None)
    monkeypatch.setenv("CT_PROJECT", "sample")
    return root


def git(root, *args) -> str:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True).stdout


def commits(root) -> int:
    return int(git(root, "rev-list", "--count", "HEAD"))


def edit_file(root, rel: str, fn) -> None:
    path = root / rel
    path.write_text(fn(path.read_text()))


# ------------------------------------------------------------------ format --

def test_unknown_answers_and_choices_are_rejected(repo):
    edit_file(repo, "requirements/processes.yml",
              lambda t: t.replace("    priority: next", "    priority: soon\n    favourite_colour: blue"))
    problems = requirements.check(project.Project("sample"))
    assert any("'soon' is not one of" in p for p in problems)
    assert any("'favourite_colour' was unexpected" in p for p in problems)


def test_references_are_checked(repo):
    edit_file(repo, "requirements/measures.yml", lambda t: t.replace("assignee: p4", "assignee: p9"))
    edit_file(repo, "requirements/sketches.yml", lambda t: t.replace("measure: cost_per_shipment", "measure: return_rate"))
    problems = requirements.check(project.Project("sample"))
    assert any("three_way_match_rate.assignee: unknown person 'p9'" in p for p in problems)
    assert any("'return_rate' is not on this dashboard" in p for p in problems)


def test_generated_files_must_be_in_step(repo):
    edit_file(repo, "seeds/process.csv", lambda t: t.replace("R2R,4,1", "R2R,4,0"))
    assert any("seeds/process.csv: out of date" in p for p in requirements.check(project.Project("sample")))


def test_an_unknown_file_is_not_a_slot(repo):
    (repo / "requirements" / "notes.yml").write_text("a: 1\n")
    assert any("notes.yml: not a requirements file" in p for p in pack.check("sample"))


# ------------------------------------------------------------------- store --

def test_an_edit_changes_only_its_own_lines(repo):
    before = {rel: (repo / rel).read_text().splitlines()
              for rel in ("requirements/measures.yml", "models/semantic/metrics.yml")}
    Store(project.current()).patch("measure", "on_time_delivery_rate",
                                   {"owner": "Logistics", "answers": {"refresh": "weekly"}}, "Dana")
    for rel, old in before.items():
        new = (repo / rel).read_text().splitlines()
        assert len(new) == len(old)
        assert [(a, b) for a, b in zip(old, new) if a != b] == [
            {"requirements/measures.yml": ("    refresh: daily", "    refresh: weekly"),
             "models/semantic/metrics.yml": ("        owner: Operations", "        owner: Logistics")}[rel]]


def test_each_save_is_one_commit_in_the_editors_name(repo):
    n = commits(repo)
    out = Store(project.current()).patch("process", "R2R", {"answers": {"volume": "Twelve closes a year"}}, "Dana Smith")
    assert commits(repo) == n + 1
    assert git(repo, "log", "-1", "--format=%an|%s") == "Dana Smith|Volume of R2R: (none) -> Twelve closes a year\n"
    changed = git(repo, "show", "--name-only", "--format=", "HEAD").split()
    assert sorted(changed) == sorted(f"projects/sample/{f}" for f in out["files"])
    assert out["entry"]["answers"]["volume"] == "Twelve closes a year"


def test_generated_files_join_the_commit(repo):
    Store(project.current()).move("process", "H2R", 0, "Dana")
    assert "projects/sample/seeds/process.csv" in git(repo, "show", "--name-only", "--format=", "HEAD")
    assert (repo / "seeds" / "process.csv").read_text().splitlines()[1] == "H2R,1,1"
    Store(project.current()).patch("measure", "return_rate", {"unknown": {"time": "Finance Controller"}}, "Dana")
    assert "| Measure Return Rate (`return_rate`) | Date and periods | Finance Controller |" \
        in (repo / "docs" / "open_questions.md").read_text()
    assert requirements.check(project.current()) == []


def test_a_save_the_lint_refuses_writes_nothing(repo):
    path = repo / "models" / "semantic" / "metrics.yml"
    before, n = path.read_text(), commits(repo)
    with pytest.raises(Refused, match="label 'Cost Per Shipment' is already used"):
        Store(project.current()).patch("measure", "return_rate", {"label": "Cost Per Shipment"}, "Dana")
    assert path.read_text() == before
    assert commits(repo) == n


def test_a_failed_commit_puts_the_files_back(repo, monkeypatch):
    store = Store(project.current())
    path = repo / "requirements" / "processes.yml"
    before = path.read_text()
    real = store._git

    def no_commit(*args, **kw):
        if args[0] == "commit":
            raise Refused("git commit failed")
        return real(*args, **kw)

    monkeypatch.setattr(store, "_git", no_commit)
    with pytest.raises(Refused):
        store.patch("process", "R2R", {"notes": "Quarter-end too"}, "Dana")
    assert path.read_text() == before
    assert git(repo, "status", "--porcelain") == ""


def test_concurrent_saves_both_land(repo):
    n = commits(repo)
    fields = {"purpose": "a", "boundaries": "b", "event": "c", "volume": "d", "decisions": "e", "pain_points": "f"}
    errors = []

    def save(k, v):
        try:
            Store(project.current()).patch("process", "H2R", {"answers": {k: v}}, f"Editor {k}")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=save, args=kv) for kv in fields.items()]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert requirements.read(project.current())["processes"]["H2R"]["answers"] == fields
    assert commits(repo) == n + len(fields)


def test_uncommitted_changes_are_never_saved_over(repo):
    edit_file(repo, "requirements/people.yml", lambda t: t + "# an engineer's edit in progress\n")
    with pytest.raises(Conflict, match="requirements/people.yml"):
        Store(project.current()).patch("person", "p1", {"email": "lead@example.com"}, "Dana")
    assert (repo / "requirements" / "people.yml").read_text().endswith("in progress\n")


def test_complete_means_every_question_answered(repo):
    store = Store(project.current())
    with pytest.raises(Refused, match="Not every question is answered yet"):
        store.patch("process", "R2R", {"interview": "complete"}, "Dana")
    # Taking an answer from a complete entry reopens it.
    store.patch("process", "O2C", {"answers": {"volume": ""}}, "Dana")
    assert requirements.read(project.current())["processes"]["O2C"]["interview"] == "in_progress"


def test_a_new_measure_is_named_from_its_label_and_placed(repo):
    store = Store(project.current())
    out = store.add("measure", None, {"label": "Order Fill Rate"}, "Dana", dashboard="O2C", slot="M4")
    assert out["key"] == "order_fill_rate"
    assert "O2C,order_fill_rate,M4,4" in (repo / "seeds" / "process_metric.csv").read_text()
    backlog = yaml.safe_load((repo / "backlog.yml").read_text())["metrics"]
    assert backlog[-1] == {"name": "order_fill_rate", "label": "Order Fill Rate", "status": "placeholder",
                           "owner": "TBD", "placeholder_reason": "Asked for in the requirements; it has no formula yet."}
    store.patch("measure", "order_fill_rate", {"label": "Fill Rate"}, "Dana")   # the name never changes
    assert "order_fill_rate" in requirements.definitions(project.current())
    with pytest.raises(Refused, match="already shows"):
        store.place("O2C", "M4", "return_rate", "Dana")
    store.remove("measure", "order_fill_rate", "Dana")
    assert "order_fill_rate" not in (repo / "seeds" / "process_metric.csv").read_text()
    assert requirements.check(project.current()) == []


def test_removing_something_still_referred_to_is_refused(repo):
    with pytest.raises(Refused, match="unknown person 'p1'"):
        Store(project.current()).remove("person", "p1", "Dana")
    with pytest.raises(Refused, match="engineering change"):
        Store(project.current()).remove("measure", "return_rate", "Dana")


def test_owner_by_person_writes_their_role(repo):
    Store(project.current()).patch("measure", "return_rate", {"owner": {"person": "p2"}}, "Dana")
    assert requirements.definitions(project.current())["return_rate"]["owner"] == "Finance"


def test_history_and_events(repo):
    store, watcher = Store(project.current()), Watcher(project.current())
    store.patch("dimension", "supplier", {"answers": {"identifier": "Supplier number in the ERP."}}, "Dana")
    store.patch("dimension", "supplier", {"answers": {"systems": ["ERP"]}}, "Lee")
    assert [h["author"] for h in store.history("dimension", "supplier")] == ["Lee", "Dana"]
    assert store.history("dimension", "carrier") == []
    change = watcher.poll()
    assert "dimensions" in change["sections"] and watcher.poll() is None


def test_the_studio_api(repo):
    from apps.studio.app import app

    client = TestClient(app)
    body = client.get("/api/requirements").json()
    assert body["project"]["slug"] == "sample" and body["problems"] == []
    assert body["measures"]["return_rate"]["definition"]["label"] == "Return Rate"
    r = client.patch("/api/requirements/dimension/carrier", json={"answers": {"identifier": "SCAC code"}},
                     headers={"X-Editor": "Jos%C3%A9"})
    assert r.status_code == 200, r.text
    assert git(repo, "log", "-1", "--format=%an") == "José\n"
    r = client.patch("/api/requirements/measure/return_rate", json={"label": "Cost Per Shipment"},
                     headers={"X-Editor": "Jos%C3%A9"})
    assert r.status_code == 422 and "already used" in r.json()["detail"]["message"]
    assert client.patch("/api/requirements/process/O2C", json={"notes": "x"}).status_code == 422  # no editor
    assert client.post("/api/requirements/dimension", json={"key": "region", "value": {"name": "Region"}},
                       headers={"X-Editor": "Jos%C3%A9"}).status_code == 201
    assert client.get("/api/requirements/history/dimension/region").json()["history"][0]["author"] == "José"


def test_dont_know_with_no_one_named_and_the_first_answer(repo):
    store = Store(project.current())
    store.patch("dimension", "employee", {"unknown": {"definition": ""}}, "Dana")
    employee = requirements.read(project.current())["dimensions"]["employee"]
    assert employee["unknown"] == {"definition": ""} and employee["interview"] == "in_progress"
    assert git(repo, "log", "-1", "--format=%s") == "Definition of employee: I don't know\n"
    store.patch("dimension", "employee", {"unknown": {"definition": None}}, "Dana")
    assert "unknown" not in requirements.read(project.current())["dimensions"]["employee"]
    # Assigning or flagging alone doesn't start the interview.
    store.patch("process", "H2R", {"assignee": "p2", "followup": True}, "Dana")
    assert "interview" not in requirements.read(project.current())["processes"]["H2R"]


def test_departments(repo):
    store = Store(project.current())
    store.add("department", "IT", {"name": "Information Technology"}, "Dana")
    rows = (repo / "seeds" / "department.csv").read_text().splitlines()
    assert rows[-2:] == ["IT,Information Technology,6", "UNASSIGNED,Unassigned,99"]
    store.patch("department", "IT", {"name": "IT"}, "Dana")
    assert "IT,IT,6" in (repo / "seeds" / "department.csv").read_text()
    store.remove("department", "IT", "Dana")
    assert "IT," not in (repo / "seeds" / "department.csv").read_text()
    with pytest.raises(Refused, match="seeds/department_metric.csv"):
        store.remove("department", "PURCH", "Dana")


def test_slots_and_systems(repo):
    store = Store(project.current())
    store.settings({"slots": 5}, "Dana")
    assert project.current().config["slots"] == 5
    with pytest.raises(Refused, match="still shows"):
        store.settings({"slots": 2}, "Dana")
    store.settings({"business_systems": ["ERP", "CRM", "Payroll", "Inventory planning", "Freight platform",
                                         "Spreadsheets"]}, "Dana")
    assert project.current().config["business_systems"]["ERP"] == "sage_x3"
    assert project.current().config["business_systems"]["Spreadsheets"] is None
    with pytest.raises(Refused, match="unknown system"):
        store.settings({"business_systems": ["CRM"]}, "Dana")


def test_removing_a_dashboard_takes_its_measures_off_it(repo):
    Store(project.current()).remove("dashboard", "P2P", "Dana")
    assert "P2P," not in (repo / "seeds" / "process_metric.csv").read_text()
    assert "three_way_match_rate" in requirements.definitions(project.current())


def test_undo(repo):
    store = Store(project.current())
    before = (repo / "requirements" / "processes.yml").read_text()
    store.patch("process", "R2R", {"answers": {"volume": "Monthly close"}}, "Dana")
    last = store.last()
    assert last["author"] == "Dana" and last["message"] == "Volume of R2R: (none) -> Monthly close"
    out = store.undo(last["commit"], "Lee")
    assert (repo / "requirements" / "processes.yml").read_text() == before
    assert out["message"] == "Undo: Volume of R2R: (none) -> Monthly close"
    assert [h["author"] for h in store.history("process", "R2R")] == ["Lee", "Dana"]
    # A save with a newer change to the same file can't be undone on its own.
    store.patch("process", "R2R", {"answers": {"volume": "Monthly"}}, "Dana")
    first = store.last()["commit"]
    store.patch("process", "H2R", {"name": "Hire to Retire (HR)"}, "Dana")
    with pytest.raises(Conflict, match="changed since"):
        store.undo(first, "Lee")
    out = store.add("measure", None, {"label": "Order Fill Rate"}, "Dana", dashboard="O2C", slot="M4")
    store.undo(store.last()["commit"], "Lee")
    assert out["key"] not in requirements.definitions(project.current())
    assert git(repo, "status", "--porcelain") == ""


def test_taking_a_measure_off_a_dashboard_takes_it_off_the_sketch(repo):
    store = Store(project.current())
    with pytest.raises(Refused, match="shows a measure once"):
        store.place("I2D", "M4", "cost_per_shipment", "Dana")
    store.place("I2D", "M1", None, "Dana")
    tiles = requirements.read(project.current())["sketches"]["I2D"]
    assert not any(t.get("measure") == "on_time_delivery_rate" for t in tiles) and len(tiles) == 10
    assert requirements.check(project.current()) == []


def test_the_studio_settings_and_undo_routes(repo):
    from apps.studio.app import app

    client = TestClient(app)
    who = {"X-Editor": "Dana"}
    assert client.put("/api/requirements/settings", json={"slots": 5}, headers=who).status_code == 200
    assert client.get("/api/requirements").json()["project"]["slots"] == 5
    r = client.post("/api/requirements/department", json={"key": "IT", "value": {"name": "IT"}}, headers=who)
    assert r.status_code == 201, r.text
    last = client.get("/api/requirements").json()["last"]
    assert last["message"] == "Add department IT"
    assert client.post("/api/requirements/undo", json={"commit": last["commit"]}, headers=who).status_code == 200
    assert "IT" not in [d["department_code"] for d in client.get("/api/requirements").json()["departments"]]
    assert client.post("/api/requirements/undo", json={"commit": "nope"}, headers=who).status_code == 404
