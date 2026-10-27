"""What the requirements show beyond their own tab: the Governance page's
definitions read from the YAML, the exports, a new project and the empty
states of a project not built yet, the bus matrix check, and dashboards laid
out as sketched. The store's own behaviour is in test_requirements.py.
"""
import os
import shutil
import subprocess

import pytest
import yaml
from fastapi.testclient import TestClient

from core import pack, project, requirements
from core.requirements import exports
from core.requirements.store import Store
from sources import generate  # noqa: F401 - loaded with the real projects, before any test moves them


def git(root, *args) -> str:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True).stdout


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """projects/sample in a scratch git repository, in use; its compiled target kept, for the catalog."""
    root = tmp_path / "projects" / "sample"
    shutil.copytree(project.Project("sample").root, root,
                    ignore=shutil.ignore_patterns("dbt_packages", "logs"))
    (tmp_path / ".gitignore").write_text("target/\n")
    for cmd in (["init", "-q"], ["config", "user.name", "Studio"], ["config", "user.email", "studio@example.com"],
                ["add", "-A"], ["commit", "-qm", "start"]):
        subprocess.run(["git", *cmd], cwd=tmp_path, check=True)
    monkeypatch.setattr(project, "PROJECTS", str(tmp_path / "projects"))
    monkeypatch.setattr(project, "_active", None)
    monkeypatch.setenv("CT_PROJECT", "sample")
    return root


# ------------------------------------------------- one measure, two views --

def test_the_catalog_refreshes_definitions_from_the_yaml(repo):
    """An owner saved through the store shows in the catalog before any dbt parse."""
    from semantic.catalog import build_catalog, refresh

    if not os.path.exists(project.current().semantic_manifest):
        pytest.skip("no semantic manifest")
    compiled = build_catalog()
    Store(project.current()).patch("measure", "return_rate", {"owner": "Finance", "description": "Returns over sales."},
                                   "Dana")
    Store(project.current()).add("measure", None, {"label": "Net Promoter Score"}, "Dana")
    fresh = {e["name"]: e for e in refresh(compiled)}
    assert fresh["return_rate"]["owner"] == "Finance"
    assert fresh["return_rate"]["description"] == "Returns over sales."
    assert fresh["return_rate"]["definition"] == {e["name"]: e for e in compiled}["return_rate"]["definition"]
    assert fresh["net_promoter_score"]["source"] == "backlog"
    assert {e["name"] for e in compiled} < set(fresh)


def test_governance_edits_save_through_the_store(repo):
    from apps.studio.app import app

    if not os.path.exists(project.current().semantic_manifest):
        pytest.skip("no semantic manifest")
    client = TestClient(app)
    r = client.patch("/api/requirements/measure/return_rate", json={"owner": "Finance"}, headers={"X-Editor": "Dana"})
    assert r.status_code == 200, r.text
    body = client.get("/api/governance").json()
    assert {m["name"]: m for m in body["metrics"]}["return_rate"]["owner"] == "Finance"
    assert body["people"]["p2"]["role"] == "Finance"
    assert client.get("/api/requirements").json()["measures"]["return_rate"]["definition"]["owner"] == "Finance"
    assert git(repo, "log", "-1", "--format=%an %s") == "Dana Owner of return_rate: TBD -> Finance\n"


# ----------------------------------------------------------------- exports --

def test_exports_are_generated_from_the_files():
    sample = project.Project("sample")
    handbook = exports.render(sample, "handbook.md")
    for heading in ("## Business processes", "## Bus matrix", "## Dimensions", "## Measures", "## Dashboards",
                    "## Ownership", "### Order to Cash", "#### On-Time Delivery"):
        assert heading in handbook, heading
    # Every question's label shows beside its answer, from questions.yml.
    assert "| Calculation |" in handbook and "| Subject matter expert |" in handbook
    rows = exports.render(sample, "measures.csv").strip().splitlines()
    assert len(rows) == 1 + len(requirements.definitions(sample))
    assert "on_time_delivery_rate,On-Time Delivery,I2D M1" in "\n".join(rows)
    bus = exports.render(sample, "bus-matrix.csv").splitlines()
    assert bus[0].startswith("business_process,records,Date,Customer")
    assert exports.render(sample, "catalogue.md").startswith("# Sample Project: measure catalogue")


def test_the_studio_serves_the_exports():
    from apps.studio.app import app

    client = TestClient(app)
    r = client.get("/api/requirements/export/measures.csv")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    assert client.get("/api/requirements/export/nothing.txt").status_code == 404


# ------------------------------------------------------------- new project --

def test_a_new_project_passes_check_pack(tmp_path, monkeypatch):
    monkeypatch.setattr(project, "PROJECTS", str(tmp_path))
    made = pack.new("acme_trial", "Acme: Trial")
    assert made.config["name"] == "Acme: Trial" and made.systems == [] and not made.has_pipeline
    assert pack.check("acme_trial") == []
    assert requirements.check(made) == []
    with pytest.raises(ValueError, match="already"):
        pack.new("acme_trial")
    with pytest.raises(ValueError, match="lower case"):
        pack.new("Acme")
    assert sorted(os.listdir(tmp_path)) == ["acme_trial"]


def test_a_built_project_still_needs_its_scenario(tmp_path, monkeypatch):
    monkeypatch.setattr(project, "PROJECTS", str(tmp_path))
    pack.new("acme_trial")
    cfg = tmp_path / "acme_trial" / "project.yml"
    cfg.write_text(cfg.read_text().replace("systems: []", "systems: [sage_x3]"))
    assert any("scenario.yml: 'seed' is required" in p for p in pack.check("acme_trial"))


def test_a_new_project_from_the_studio_is_committed_and_works(repo):
    from apps.studio.app import app

    client = TestClient(app)
    try:
        assert client.post("/api/projects", json={"slug": "acme", "name": "Acme"}).status_code == 422  # no editor
        r = client.post("/api/projects", json={"slug": "acme", "name": "Acme"}, headers={"X-Editor": "Dana"})
        assert r.status_code == 201, r.text
        assert r.json()["current"] == "acme"
        root = repo.parent / "acme"
        assert git(root, "status", "--porcelain", "--", ".") == ""
        assert git(root, "log", "-1", "--format=%an %s") == "Dana New project Acme\n"
        # Requirements work from the first save; the other tabs say it isn't built.
        h = {"X-Editor": "Dana"}
        assert client.post("/api/requirements/process", json={"key": "O2C", "value": {"name": "Order to Cash"}},
                           headers=h).status_code == 201
        assert client.post("/api/requirements/dashboard", json={"key": "O2C", "value": {"name": "Order to Cash"}},
                           headers=h).status_code == 201
        r = client.post("/api/requirements/measure", json={"value": {"label": "Fill Rate"}, "dashboard": "O2C",
                                                           "slot": "M1"}, headers=h)
        assert r.status_code == 201, r.text
        assert pack.check("acme") == []
        snap = client.get("/api/requirements").json()
        assert snap["problems"] == [] and snap["measures"]["fill_rate"]["placements"][0]["slot"] == "M1"
        assert snap["last"]["undoable"] is True
        state = client.get("/api/state").json()
        assert state["project"]["pipeline"] is False and state["clock"] == {"initialised": False, "pipeline": False}
        for path in ("/api/dashboards", "/api/governance", "/api/metrics", "/api/query/schema"):
            r = client.get(path)
            assert r.status_code == 409 and "isn't built yet" in r.json()["detail"], path
        assert client.post("/api/run", json={"steps": ["day"]}).status_code == 409
        assert client.get("/api/requirements/coverage").json()["available"] is False
        assert client.get("/api/map").status_code == 200
        assert client.get("/api/requirements/export/handbook.md").status_code == 200
    finally:
        client.post("/api/project", json={"slug": "sample"})


def test_making_the_project_is_not_undone(repo, tmp_path):
    pack.new("acme")
    store = Store(project.Project("acme"))
    store.created("Dana")
    last = store.last()
    assert last["undoable"] is False
    with pytest.raises(Exception, match="isn't undone here"):
        store.undo(last["commit"], "Dana")


# ------------------------------------------------- the build, checked live --

def test_a_dimension_code_honours_entities_attributes_and_time():
    from apps.studio.governance import cuts

    assert cuts("customer__customer_name", "customer")
    assert cuts("employee__department_name", "employee") and cuts("employee__department_name", "department")
    assert cuts("metric_time__month", "date") and not cuts("customer__first_seen_date", "date")
    assert not cuts("site__site_name", "customer")


def test_the_bus_matrix_coverage_and_sketched_pages():
    import datetime as dt

    from apps.studio import data
    from apps.studio.app import app
    from core.settings import settings

    sample = project.Project("sample")
    if project.slug() != "sample" or not os.path.exists(sample.semantic_manifest):
        pytest.skip("runs on the sample project, compiled")
    cov = TestClient(app).get("/api/requirements/coverage").json()
    assert cov["available"] and "carrier" in cov["metrics"]["on_time_delivery_rate"]
    assert "supplier" not in cov["metrics"]["on_time_delivery_rate"]
    if not os.path.exists(settings.warehouse_path):
        pytest.skip("no warehouse")
    sk = data.sketch("mart_i2d", "month", dt.date.today())
    tiles = {(t["kind"], t.get("dimension")): t for t in sk["tiles"]}
    assert tiles[("filter", "date")]["cube_dim"] == "metric_time__month"
    assert "doesn't carry Carrier" in tiles[("bar", "carrier")]["issue"]
    line = tiles[("line", None)]
    assert sk["parts"][line["part"]]["metric"] == "on_time_delivery_rate"
    assert {c["metric"] for c in sk["base"]["cards"]} >= {t["measure"] for t in sk["tiles"] if t["kind"] == "kpi"}


def test_the_old_handoff_is_gone():
    from core.settings import ROOT

    for rel in ("semantic/requirements_spec.schema.json", "docs/requirements_contract.md"):
        assert not os.path.exists(os.path.join(ROOT, rel))
    skill = os.path.join(ROOT, ".claude", "skills", "build-from-requirements", "SKILL.md")
    with open(skill) as fh:
        head = yaml.safe_load(fh.read().split("---")[1])
    assert head["name"] == "build-from-requirements"
