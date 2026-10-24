"""The Studio's map stays true to the component registry, and its pipeline to the step commands."""
import yaml
from fastapi.testclient import TestClient

from apps.studio import pipeline
from apps.studio.app import COMPONENTS, app
from apps.studio.probe import PROBES
from ctl.__main__ import STAGES


def test_map_matches_the_component_registry():
    with open(COMPONENTS) as fh:
        registry = yaml.safe_load(fh)["components"]
    body = TestClient(app).get("/api/map").json()
    nodes = {n["id"]: n for n in body["nodes"] + body["foundation"]}
    for n in nodes.values():
        assert not n.get("component") or n["component"] in registry, n["id"]
        assert set(n["stacks"]) == {s["id"] for s in body["stacks"]}
    for e in body["edges"]:
        assert e["from"] in nodes and e["to"] in nodes, e
        assert not e.get("contract") or e["contract"] in body["contracts"], e
    assert set(body["contracts"]) == {f"C{i}" for i in range(1, 8)}


def test_every_step_runs_real_commands_and_has_a_probe():
    for step in pipeline.STEPS + [pipeline.RESET]:
        assert step is pipeline.RESET or step["id"] in PROBES
        for cmd in step["commands"]:
            assert cmd[0] == "ctl"
            if cmd[1] == "build":
                assert cmd[cmd.index("--stage") + 1] in STAGES


def test_dbt_progress_is_read_from_the_log():
    assert pipeline.progress("12 of 45 OK created sql table model gold.dim_site") == (12, 45)
    assert pipeline.progress("3 of 45 START sql table model gold.dim_site") is None
    assert pipeline.facts_from_log("collect", ["hubspot          163 rows"])[0]["raw"] == 163


def test_every_contract_shows_real_files_and_runnable_suites():
    import os

    from apps.studio import contracts
    from core.settings import ROOT

    with open(os.path.join(ROOT, "apps", "studio", "content.yml")) as fh:
        content = yaml.safe_load(fh)
    for cid, c in content["contracts"].items():
        assert c["files"], cid
        for f in c["files"]:
            assert contracts.excerpt(f)["text"], f["path"]
        for suite in c["suites"]:
            assert contracts.command(suite, live=True)
            if suite["kind"] == "pytest":
                assert os.path.exists(os.path.join(ROOT, suite["path"])), suite["path"]
                assert contracts.cases(suite), suite["path"]
        assert c["suites"] or c.get("enforced"), cid


def test_sql_editor_runs_one_read_query_only():
    import pytest

    from apps.studio import data

    for ok in ("select 1", "  WITH x as (select 1) select * from x", "describe gold.dim_site"):
        assert data.ALLOWED.match(ok), ok
    for bad, why in (("drop table gold.dim_site", "Only read"), ("select 1; select 2", "One statement"),
                     ("copy gold.dim_site to 'x.csv'", "Only read"), ("", "Write a query")):
        with pytest.raises(ValueError, match=why):
            data.run_sql(bad)


def test_pipeline_lock_admits_one_writer(isolated_data):
    import pytest

    from core.lock import PipelineBusy, held, holder

    with held("python -m ctl run"):
        assert holder()["command"] == "python -m ctl run"
        with pytest.raises(PipelineBusy, match="python -m ctl run"):
            with held("python -m ctl build"):
                pass
    assert holder() is None


def test_chat_streams_each_tool_call_then_the_answer(monkeypatch):
    import json

    import pytest

    pytest.importorskip("anthropic")
    from apps.examples.ask_metrics import app as ask_app
    from apps.studio import app as studio

    def fake_ask(question, history=None):
        ask_app.on_tool.get()("query_metrics", {"metrics": ["revenue"], "group_by": None}, {"rows": [[1], [2]]})
        return f"Answer to: {question}"

    monkeypatch.setattr(studio, "ask_status", lambda: {"available": True, "model": "test"})
    monkeypatch.setattr(studio, "_readable", lambda: None)
    monkeypatch.setattr(studio, "_svc", lambda: ask_app.svc)
    monkeypatch.setattr(ask_app, "ask", fake_ask)
    r = TestClient(app).post("/api/ask", json={"question": "Revenue?", "history": []})
    events = [json.loads(line) for line in r.text.splitlines() if line]
    assert events[0] == {"type": "tool", "tool": "query_metrics", "input": {"metrics": ["revenue"]},
                         "summary": "2 rows"}
    assert events[-1] == {"type": "answer", "text": "Answer to: Revenue?"}


def test_dashboard_periods_compare_like_with_like():
    import datetime as dt

    from apps.studio import data

    aug = dt.date(2026, 8, 1)
    month = data._windows("month", aug)
    assert month["cur"][:2] == (aug, aug)
    assert month["prev"][:2] == (dt.date(2026, 7, 1),) * 2
    assert month["py"][:2] == (dt.date(2025, 8, 1),) * 2
    qtd = data._windows("qtd", aug)
    assert qtd["cur"][:2] == (dt.date(2026, 7, 1), aug)
    assert qtd["prev"][:2] == (dt.date(2026, 4, 1), dt.date(2026, 5, 1))
    ytd = data._windows("ytd", aug)
    assert set(ytd) == {"cur", "py"} and ytd["py"][:2] == (dt.date(2025, 1, 1), dt.date(2025, 8, 1))
    assert data._windows("12m", aug)["cur"][0] == dt.date(2025, 9, 1)


def test_dashboard_cards_are_the_cube_rows_metricflow_wrote():
    """A card over one month is the measure template over one stored row: MetricFlow's own number."""
    import datetime as dt
    import os

    import pytest

    from apps.studio import data
    from core.settings import settings

    if not os.path.exists(settings.warehouse_path):
        pytest.skip("no warehouse")
    name = "mart_company_monthly"
    _, rows = data._read("select max(metric_time__month) from marts.dashboard_cube "
                         "where _cube = ? and revenue is not null", [name])
    latest = dt.date.fromisoformat(rows[0][0])
    asof = data._shift(latest, -1)
    page = data.page(name, None, "month", dt.date(latest.year, latest.month, 2), asof)
    assert page["asof"] == asof.isoformat() and not page["window"]["partial"]
    cols = [c["metric"] for c in page["cards"]]
    _, stored = data._read(f"select {', '.join(repr(c).replace(chr(39), chr(34)) for c in cols)} from marts.dashboard_cube "
                           "where _cube = ? and metric_time__month = ?", [name, asof])
    for card, value in zip(page["cards"], stored[0]):
        assert card["value"] == (None if value is None else pytest.approx(value)), card["metric"]
