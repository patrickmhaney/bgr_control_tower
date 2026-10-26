"""check-pack: every pack passes, and a pack that strays from the layout fails."""
import os
import shutil

import pytest
import yaml

from core import pack, project


@pytest.mark.parametrize("slug", project.available())
def test_every_pack_passes(slug):
    assert pack.check(slug) == []


@pytest.fixture
def copy(tmp_path, monkeypatch):
    """A copy of sample_v2 in a scratch projects folder."""
    shutil.copytree(project.Project("sample_v2").root, tmp_path / "scratch",
                    ignore=shutil.ignore_patterns("target", "dbt_packages", "logs"))
    cfg = tmp_path / "scratch" / "project.yml"
    cfg.write_text(cfg.read_text().replace("slug: sample_v2", "slug: scratch"))
    dbt = tmp_path / "scratch" / "dbt_project.yml"
    dbt.write_text(dbt.read_text().replace("sample_v2", "scratch"))
    monkeypatch.setattr(project, "PROJECTS", str(tmp_path))
    return tmp_path / "scratch"


def test_the_copy_passes(copy):
    assert pack.check("scratch") == []


def test_python_is_rejected(copy):
    (copy / "models" / "gold" / "helper.py").write_text("x = 1\n")
    assert any("no Python" in p for p in pack.check("scratch"))


def test_a_staging_layer_in_the_pack_is_rejected(copy):
    os.makedirs(copy / "models" / "silver" / "staging")
    (copy / "models" / "silver" / "staging" / "stg_x.sql").write_text("select 1\n")
    assert any("not in a pack slot" in p for p in pack.check("scratch"))


def test_layer_settings_cannot_change(copy):
    dbt = copy / "dbt_project.yml"
    doc = yaml.safe_load(dbt.read_text())
    doc["models"]["scratch"]["gold"]["+materialized"] = "view"
    dbt.write_text(yaml.safe_dump(doc))
    assert any("'models' differs" in p for p in pack.check("scratch"))


def test_vars_may_change(copy):
    dbt = copy / "dbt_project.yml"
    doc = yaml.safe_load(dbt.read_text())
    doc["vars"]["fiscal_year_start_month"] = 7
    dbt.write_text(yaml.safe_dump(doc))
    assert pack.check("scratch") == []


def test_unknown_scenario_key_is_rejected(copy):
    sc = copy / "scenario.yml"
    sc.write_text(sc.read_text() + "\nextra_setting: 1\n")
    assert any("unknown key 'extra_setting'" in p for p in pack.check("scratch"))


def test_every_spec_table_needs_a_bronze_model(copy):
    os.remove(copy / "models" / "bronze" / "bronze_hubspot__deal.sql")
    assert any("bronze_hubspot__deal.sql: missing" in p for p in pack.check("scratch"))


def test_architecture_pin_must_match(copy):
    cfg = copy / "project.yml"
    cfg.write_text(cfg.read_text().replace("architecture: 3.0.0", "architecture: 2.9.0"))
    assert any("pinned to architecture" in p for p in pack.check("scratch"))
