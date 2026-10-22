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
