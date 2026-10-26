"""check-pack: a project pack fills the fixed slots, and nothing else.

    python -m ctl check-pack [slug]

The architecture is identical for every project; a pack only supplies content
(PLAN.md §6). This is how that is enforced rather than intended. A pack is
rejected when it holds:

* Python, or any file outside the layout below
* models outside bronze, silver (intermediate, conformed) and gold, or SQL
  in the semantic folder; staging adapters belong to the platform package
* a dbt_project.yml that differs from transform/platform/project_template.yml
  beyond `name` (which must be the slug) and `vars`
* a packages.yml without the platform package
* unknown keys in project.yml or scenario.yml, or a system with no simulator
  and staging adapter in the architecture
* an architecture pin that differs from the platform version
* a spec table with no bronze model, or a bronze model with no spec table

    projects/<slug>/
      project.yml  scenario.yml  dbt_project.yml  packages.yml
      ingestion/specs/<system>.yml  ingestion/schemas/<system>.schema.yaml
      models/bronze/  models/silver/intermediate/  models/silver/conformed/
      models/gold/  models/semantic/*.yml
      seeds/*.csv|yml  tests/*.sql  backlog.yml  golden_answers.yml
      powerbi/ (generated)  docs/*.md  dashboards.yml (optional)
"""
from __future__ import annotations

import fnmatch
import os
import sys

import yaml

from core import project

#: Top-level entries a pack may hold. dbt and git leave the ignored ones behind.
TOP = {"project.yml", "scenario.yml", "dbt_project.yml", "packages.yml", "package-lock.yml",
       "ingestion", "models", "seeds", "tests", "backlog.yml", "golden_answers.yml", "powerbi",
       "docs", "dashboards.yml", "README.md"}
IGNORED = {"target", "dbt_packages", "logs", ".user.yml", ".DS_Store", "__pycache__"}
#: Where each kind of file may live, relative to the pack.
ALLOWED = [
    "ingestion/specs/*.yml", "ingestion/schemas/*.schema.yaml",
    "models/bronze/*.sql", "models/bronze/*.yml",
    "models/silver/intermediate/*.sql", "models/silver/intermediate/*.yml",
    "models/silver/conformed/*.sql", "models/silver/conformed/*.yml",
    "models/gold/*.sql", "models/gold/*.yml",
    "models/semantic/*.yml",
    "seeds/*.csv", "seeds/*.yml", "tests/*.sql", "docs/*.md",
    "powerbi/*",
]
PROJECT_KEYS = {"name", "slug", "systems", "mdm_provider", "architecture", "description"}
PROJECT_REQUIRED = {"name", "slug", "systems", "architecture"}


def _files(root: str) -> list[str]:
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORED]
        out += [os.path.relpath(os.path.join(dirpath, f), root) for f in filenames if f not in IGNORED]
    return sorted(out)


def _yaml(path: str) -> dict:
    with open(path) as fh:
        return yaml.safe_load(fh) or {}


def platform_version() -> str:
    return str(_yaml(os.path.join(project.PLATFORM, "dbt_project.yml"))["version"])


def known_systems() -> set[str]:
    """Systems the architecture can simulate and stage: in sources/systems.yml,
    with a simulator and a staging adapter."""
    registry = set(_yaml(os.path.join(project.ROOT, "sources", "systems.yml")))
    sims = {f[:-3] for f in os.listdir(os.path.join(project.ROOT, "sources", "simulators"))
            if f.endswith(".py") and not f.startswith("_")}
    staging = set(os.listdir(os.path.join(project.PLATFORM, "models", "silver", "staging")))
    return registry & sims & staging


def check(slug: str) -> list[str]:
    from sources.generate import OPTIONAL_SCENARIO_KEYS, SCENARIO_KEYS

    pack = project.Project(slug)
    root = pack.root
    if not os.path.isdir(root):
        return [f"no pack at {os.path.relpath(root, project.ROOT)}"]
    problems = []

    for entry in sorted(set(os.listdir(root)) - TOP - IGNORED):
        problems.append(f"{entry}: not part of the pack layout")
    for rel in _files(root):
        if rel.endswith(".py"):
            problems.append(f"{rel}: a pack holds no Python - new mechanics belong in the architecture")
        elif os.sep in rel and not rel.startswith("powerbi" + os.sep) \
                and not any(fnmatch.fnmatch(rel, pat) for pat in ALLOWED):
            problems.append(f"{rel}: not in a pack slot")
    for required in ("project.yml", "scenario.yml", "dbt_project.yml", "packages.yml",
                     "backlog.yml", "golden_answers.yml"):
        if not os.path.isfile(os.path.join(root, required)):
            problems.append(f"{required}: missing")
    if problems:
        return problems

    # project.yml
    cfg = _yaml(pack.path("project.yml"))
    for key in sorted(set(cfg) - PROJECT_KEYS):
        problems.append(f"project.yml: unknown key {key!r}")
    for key in sorted(PROJECT_REQUIRED - set(cfg)):
        problems.append(f"project.yml: {key!r} is required")
    if cfg.get("slug") != slug:
        problems.append(f"project.yml: slug must be {slug!r}, the folder name")
    systems = set(cfg.get("systems") or [])
    for s in sorted(systems - known_systems()):
        problems.append(f"project.yml: system {s!r} has no simulator and staging adapter in the architecture")
    if str(cfg.get("architecture")) != platform_version():
        problems.append(f"project.yml: pinned to architecture {cfg.get('architecture')}, "
                        f"the platform is {platform_version()} - upgrading is a reviewed change")

    # scenario.yml
    scenario = _yaml(pack.scenario)
    for key in sorted(set(scenario) - SCENARIO_KEYS):
        problems.append(f"scenario.yml: unknown key {key!r}")
    for key in sorted(SCENARIO_KEYS - OPTIONAL_SCENARIO_KEYS - set(scenario)):
        problems.append(f"scenario.yml: {key!r} is required")

    # dbt_project.yml: the template, with only name and vars filled in
    template = _yaml(os.path.join(project.PLATFORM, "project_template.yml"))
    template = yaml.safe_load(yaml.safe_dump(template).replace("__project__", slug))
    mine = _yaml(pack.path("dbt_project.yml"))
    if mine.get("name") != slug:
        problems.append(f"dbt_project.yml: name must be {slug!r}")
    for key in sorted(set(template) | set(mine)):
        if key in ("name", "vars"):
            continue
        if template.get(key) != mine.get(key):
            problems.append(f"dbt_project.yml: {key!r} differs from transform/platform/project_template.yml")

    # packages.yml: the platform package, local (samples) or pinned (client repos)
    pkgs = _yaml(pack.path("packages.yml")).get("packages") or []
    if not any(str(p.get("local", "")).rstrip("/").endswith("transform/platform")
               or p.get("subdirectory", "").rstrip("/") == "transform/platform" for p in pkgs):
        problems.append("packages.yml: must depend on the platform package (transform/platform)")

    # ingestion: one spec and one frozen schema per system; one bronze model per spec table
    specs = {f[:-4] for f in os.listdir(pack.specs) if f.endswith(".yml")} if os.path.isdir(pack.specs) else set()
    for s in sorted(systems - specs):
        problems.append(f"ingestion/specs/{s}.yml: missing for system {s!r}")
    for s in sorted(specs - systems):
        problems.append(f"ingestion/specs/{s}.yml: {s!r} is not in project.yml systems")
    expected = set()
    for s in sorted(specs & systems):
        if not os.path.isfile(os.path.join(pack.schemas, f"{s}.schema.yaml")):
            problems.append(f"ingestion/schemas/{s}.schema.yaml: missing (freeze it on the first run)")
        for table in _yaml(os.path.join(pack.specs, f"{s}.yml")).get("tables") or {}:
            expected.add(f"bronze_{s}__{table.lower()}")
    bronze = {f[:-4] for f in os.listdir(os.path.join(pack.models, "bronze")) if f.endswith(".sql")} \
        if os.path.isdir(os.path.join(pack.models, "bronze")) else set()
    for m in sorted(expected - bronze):
        problems.append(f"models/bronze/{m}.sql: missing - one bronze model per spec table")
    for m in sorted(bronze - expected):
        problems.append(f"models/bronze/{m}.sql: no spec table behind it")
    return problems


def main(slug: str) -> None:
    problems = check(slug)
    for p in problems:
        print(f"check-pack {slug}: {p}")
    print(f"check-pack {slug}: ok" if not problems else f"check-pack {slug}: {len(problems)} problem(s)")
    sys.exit(1 if problems else 0)
