"""The one-time converter from the governance tool's database (core/requirements/convert).

The coverage test: every column of the tool's database has a home in a
project, or a reason it is dropped. Then a small workspace, built on the tool's
own schema, converted into a copy of projects/sample.
"""
import json
import os
import shutil
import sqlite3

import pytest
import yaml

from core import project, requirements
from core.requirements import convert, store

SCHEMA = os.path.join(os.path.dirname(__file__), "..", "fixtures", "governance_schema.sql")
LIVE = os.path.join(project.ROOT, "..", "lo_governance_guide", "data", "requirements.db")
HOMES = ("requirements/", "seeds/", "project.yml", "the semantic files", "the metric's name", "the slot shows",
         "dropped: ")


def database() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    with open(SCHEMA) as fh:
        conn.executescript(fh.read())
    return conn


def test_every_column_has_a_home():
    assert convert.coverage_problems(database()) == []
    for table, columns in convert.COLUMNS.items():
        for column, home in columns.items():
            assert home.startswith(HOMES), f"{table}.{column}: {home!r} names no home"


@pytest.mark.skipif(not os.path.exists(LIVE), reason="the governance tool is not checked out next to this repo")
def test_the_live_database_matches_the_schema():
    conn = sqlite3.connect(f"file:{LIVE}?mode=ro", uri=True)
    assert convert.coverage_problems(conn) == []


def test_a_column_nobody_mapped_is_refused():
    conn = database()
    conn.execute("ALTER TABLE processes ADD COLUMN mood TEXT")
    conn.execute("INSERT INTO clients (slug, name, created_at) VALUES ('w', 'W', 'now')")
    with pytest.raises(convert.ConvertError, match="processes.mood: not in COLUMNS"):
        convert.Workspace(conn, "w")


def workspace() -> sqlite3.Connection:
    """A small workspace: two processes, two dimensions, a process dashboard with
    an existing KPI and a new measure, and a non-process dashboard showing one."""
    conn = database()
    q = conn.execute
    q("INSERT INTO clients VALUES (1, 'demo', 'Sample Project', 4, ?, 1, 'now', 'sample')",
      (json.dumps(["ERP", "CRM", "Payroll", "Inventory planning", "Freight platform"]),))
    for i, (code, name, pos) in enumerate([("SALES", "Sales", 1), ("CUSTSVC", "Customer Service", 2),
                                           ("OPS", "Operations", 3), ("PURCH", "Procurement", 4),
                                           ("FIN", "Finance", 5), ("UNASSIGNED", "Unassigned", 99)], 1):
        q("INSERT INTO departments VALUES (?, 1, ?, ?, ?)", (i, name, code, pos))
    q("INSERT INTO people VALUES (7, 1, 'Dana Example', 'Customer Service', 'dana@example.com', 'now', 2)")
    q("""INSERT INTO processes (id, client_id, position, name, code, answers, unknown, owner_id, status)
         VALUES (1, 1, 0, 'Order to Cash', 'O2C', ?, ?, 7, 'in_progress')""",
      (json.dumps({"purpose": "Turns orders into cash.", "systems": ["ERP", " "], "pain_points_none": True}),
       json.dumps({"volume": "Sales Ops"})))
    q("INSERT INTO processes (id, client_id, position, name, code) VALUES (2, 1, 1, 'Inventory to Delivery', 'I2D')")
    q("INSERT INTO processes (id, client_id, position, name) VALUES (3, 1, 2, '')")  # a draft: skipped
    q("INSERT INTO process_steps VALUES (1, 1, 0, 'Take the order', 1, NULL, 'CRM')")
    q("INSERT INTO process_steps VALUES (2, 1, 1, 'Ship', NULL, 7, 'ERP')")
    q("INSERT INTO dimensions (id, client_id, position, name, code, answers) VALUES (1, 1, 0, 'Date', 'date', '{}')")
    q("""INSERT INTO dimensions (id, client_id, position, name, code, answers, owner_dept_id, status)
         VALUES (2, 1, 1, 'Customer', 'customer', ?, 2, 'in_progress')""",
      (json.dumps({"definition": "Anyone who buys.", "history": "as_was"}),))
    q("INSERT INTO bus_cells VALUES (1, 2), (1, 1)")
    q("INSERT INTO dashboards VALUES (1, 1, 'O2C', 'Order to Cash', 0, '', '', '', '')")
    q("INSERT INTO dashboards VALUES (2, 1, 'I2D', 'Inventory to Delivery', 1, '', '', '', '')")
    q("INSERT INTO dashboards VALUES (3, 1, 'OPS', 'Operations', 2, 'The ops director.', '', 'Monthly.', '')")
    q("""INSERT INTO requirements (id, dashboard_id, slot, name, description, metric_name, owner_id, notes,
                                   formula, sources, dimension_ids, refresh, sme_id, status, unknown, process_id)
         VALUES (1, 1, 1, 'Return Rate', 'The share of sales that come back.', 'return_rate', 7,
                 'Credits only.' || char(10) || 'Dated on the order.', 'Returns over sales.', '["ERP"]', '[2, 1]',
                 'weekly', 7, 'in_progress', '{"target": "Finance"}', 1)""")
    q("""INSERT INTO requirements (id, dashboard_id, slot, name, description, status, followup, followup_note, binding)
         VALUES (2, 1, 2, 'Net Promoter Score', '', 'not_started', 1, 'Who runs the survey?',
                 '{"backlog": {"status": "blocked", "reason": "No survey source.", "unblock_requires": ["A survey"]}}')""")
    q("INSERT INTO requirements (id, dashboard_id, slot) VALUES (3, 1, 3)")             # an empty slot
    q("INSERT INTO requirements (id, dashboard_id, slot, ref_id) VALUES (4, 3, 2, 1)")  # also on Operations
    q("INSERT INTO measure_departments VALUES (1, 1, 2, 1, 'owns', 0)")
    q("INSERT INTO tiles VALUES (1, 1, 'kpi', 0, 1, 3, 2, '', 1, NULL, '')")
    q("INSERT INTO tiles VALUES (2, 1, 'filter', 0, 0, 3, 1, '', NULL, 1, '')")
    q("INSERT INTO activity VALUES (1, 1, 'now', 7, 'edited', 'x')")
    return conn


@pytest.fixture
def sample(tmp_path, monkeypatch):
    """A copy of projects/sample to convert into."""
    root = tmp_path / "projects" / "sample"
    shutil.copytree(project.Project("sample").root, root,
                    ignore=shutil.ignore_patterns("target", "dbt_packages", "logs"))
    monkeypatch.setattr(project, "PROJECTS", str(tmp_path / "projects"))
    return project.Project("sample")


def run(conn, pack) -> tuple[dict[str, str], list[str]]:
    texts, notes = convert.convert(conn, "demo", pack)
    for rel, text in texts.items():
        store._write(pack.path(rel), text)
    return texts, notes


def test_convert_a_workspace(sample):
    texts, notes = run(workspace(), sample)
    pack = project.Project("sample")
    docs = requirements.read(pack)

    # People by id; the name only in people.yml, the role where an owner is shown.
    assert docs["people"] == {"p1": {"name": "Dana Example", "role": "Customer Service",
                                     "email": "dana@example.com", "department": "CUSTSVC"}}
    assert all("Dana" not in text for rel, text in texts.items() if rel != "requirements/people.yml")

    o2c = docs["processes"]["O2C"]
    assert list(docs["processes"]) == ["O2C", "I2D"]
    assert o2c["answers"]["steps"] == [{"name": "Take the order", "department": "SALES", "system": "CRM"},
                                       {"name": "Ship", "person": "p1", "system": "ERP"}]
    assert o2c["answers"]["systems"] == ["ERP"] and o2c["answers"]["pain_points_none"] is True
    assert o2c["answers"]["owner"] == {"person": "p1"} and o2c["unknown"] == {"volume": "Sales Ops"}
    assert docs["dimensions"]["customer"]["answers"]["owner"] == {"department": "CUSTSVC"}
    assert docs["bus_matrix"] == {"O2C": ["date", "customer"]}
    assert docs["dashboards"]["OPS"] == {"name": "Operations", "audience": "The ops director.",
                                         "cadence": "Monthly.", "slots": {"M2": "return_rate"}}

    # Answers in measures.yml; the definition in the semantic files.
    rr = docs["measures"]["return_rate"]
    assert rr["answers"]["dimensions"] == ["customer", "date"] and rr["answers"]["sme"] == {"person": "p1"}
    assert rr["unknown"] == {"target": "Finance"} and "process" not in rr
    defs = requirements.definitions(pack)
    assert defs["return_rate"]["owner"] == "Customer Service"
    assert defs["return_rate"]["caveats"] == ["Credits only.", "Dated on the order."]
    nps = defs["net_promoter_score"]
    assert (nps["file"], nps["status"], nps["label"]) == ("backlog.yml", "blocked", "Net Promoter Score")
    assert docs["measures"]["net_promoter_score"]["followup_note"] == "Who runs the survey?"

    assert texts["seeds/process_metric.csv"].splitlines()[1:] == [
        "O2C,return_rate,M1,1", "O2C,net_promoter_score,M2,2"]
    assert texts["seeds/department_metric.csv"].splitlines()[1:] == ["CUSTSVC,O2C,return_rate,owns"]
    assert texts["seeds/process.csv"].splitlines()[1:] == ["O2C,1,1", "I2D,2,1"]
    assert yaml.safe_load(texts["requirements/sketches.yml"]) == {"O2C": [
        {"kind": "filter", "x": 0, "y": 0, "w": 3, "h": 1, "dimension": "date"},
        {"kind": "kpi", "x": 0, "y": 1, "w": 3, "h": 2, "measure": "return_rate"}]}
    assert "project.yml" not in texts  # slots and systems already as the workspace has them

    # The project is sound, KPIs the workspace doesn't name are reported, and it converges.
    assert requirements.check(pack) == []
    assert any("on_time_delivery_rate is not in the workspace" in n for n in notes)
    assert convert.convert(workspace(), "demo", project.Project("sample"))[0] == {}
