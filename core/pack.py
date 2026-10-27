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
* requirements/ files that break their schemas or refer to codes, people or
  metrics that don't exist, or a generated seed out of step with them
  (core/requirements)

A project with no source systems yet (`systems: []`) is in requirements only:
it has nothing to generate, so its scenario.yml may be empty. `new()` makes one.

    projects/<slug>/
      project.yml  scenario.yml  dbt_project.yml  packages.yml
      ingestion/specs/<system>.yml  ingestion/schemas/<system>.schema.yaml
      models/bronze/  models/silver/intermediate/  models/silver/conformed/
      models/gold/  models/semantic/*.yml
      seeds/*.csv|yml  tests/*.sql  backlog.yml  golden_answers.yml
      powerbi/ (generated)  docs/*.md  dashboards.yml (optional)
      requirements/*.yml (optional; core/requirements lists the files)
"""
from __future__ import annotations

import fnmatch
import os
import re
import sys

import yaml

from core import project, requirements

#: Top-level entries a pack may hold. dbt and git leave the ignored ones behind.
TOP = {"project.yml", "scenario.yml", "dbt_project.yml", "packages.yml", "package-lock.yml",
       "ingestion", "models", "seeds", "tests", "backlog.yml", "golden_answers.yml", "powerbi",
       "docs", "dashboards.yml", "README.md", "requirements"}
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
    "powerbi/*", "requirements/*",
]
PROJECT_KEYS = {"name", "slug", "systems", "mdm_provider", "architecture", "description",
                "slots", "business_systems"}
MAX_SLOTS = 12
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
    for name, system in (cfg.get("business_systems") or {}).items():
        if system is not None and system not in systems:
            problems.append(f"project.yml: business system {name!r} maps to {system!r}, which is not in systems")
    if "slots" in cfg and not (isinstance(cfg["slots"], int) and 1 <= cfg["slots"] <= MAX_SLOTS):
        problems.append(f"project.yml: slots must be a whole number from 1 to {MAX_SLOTS}")
    if str(cfg.get("architecture")) != platform_version():
        problems.append(f"project.yml: pinned to architecture {cfg.get('architecture')}, "
                        f"the platform is {platform_version()} - upgrading is a reviewed change")

    # scenario.yml: required once there are sources to simulate
    scenario = _yaml(pack.scenario)
    for key in sorted(set(scenario) - SCENARIO_KEYS):
        problems.append(f"scenario.yml: unknown key {key!r}")
    for key in sorted(SCENARIO_KEYS - OPTIONAL_SCENARIO_KEYS - set(scenario) if systems else ()):
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

    # requirements: an optional slot, checked against its schemas and the rest of the pack
    if os.path.isdir(pack.requirements):
        problems += requirements.check(pack)
    return problems


def main(slug: str) -> None:
    problems = check(slug)
    for p in problems:
        print(f"check-pack {slug}: {p}")
    print(f"check-pack {slug}: ok" if not problems else f"check-pack {slug}: {len(problems)} problem(s)")
    sys.exit(1 if problems else 0)


# -------------------------------------------------------------- new project --

#: What a new project's files say about themselves. It starts in requirements
#: only; the build-from-requirements skill adds the build logic.
_HEADERS = {
    "people": "The people the requirements name, by id: who owns, who answers, who follows\n"
              "up. The only file in the project with names in it; every other file refers\n"
              "to a person by id. A metric's owner in the semantic files is a role, so\n"
              "picking a person as owner writes their role.",
    "processes": "Business processes, by code, in display order: the rows of the bus matrix.\n"
                 "seeds/process.csv is generated from this file. Questions: core/requirements/questions.yml.",
    "dimensions": "Dimensions, by code, in display order: what the business is measured by, and\n"
                  "the columns of the bus matrix. Questions: core/requirements/questions.yml.",
    "bus_matrix": "The bus matrix: each process and the dimensions it is analysed by.",
    "dashboards": "Dashboards, by code, in display order: the rows of the Measures grid, and how\n"
                  "each is used. A process dashboard (its code is a process code) takes its\n"
                  "measures from seeds/process_metric.csv; any other lists them in `slots`.",
    "measures": "Each measure's discovery answers, by metric name. Its label, description,\n"
                "owner and caveats are its definition, in the semantic files\n"
                "(models/semantic/metrics.yml, or backlog.yml until it has a formula).\n"
                "Questions: core/requirements/questions.yml.",
    "sketches": "Dashboard sketches, by dashboard code: tiles on a 12-column grid.\n"
                "Tile kinds: core/requirements/questions.yml (tiles).",
}


def _comment(text: str) -> str:
    return "".join(f"# {line}\n" if line else "#\n" for line in text.split("\n"))


def new(slug: str, name: str | None = None) -> project.Project:
    """A project folder in requirements only: the platform's dbt template,
    empty seeds and semantic files, an empty scenario and requirements/. It
    passes check-pack as it is; nothing is committed."""
    from checks import blocked_words

    name = " ".join((name or slug.replace("_", " ").title()).split())
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,39}", slug or ""):
        raise ValueError("A project's folder name is lower case letters, digits and _, starting with a letter")
    if os.path.exists(os.path.join(project.PROJECTS, slug)):
        raise ValueError(f"There is already a project {slug!r}")
    if blocked_words.found(f"{slug} {name}"):
        raise ValueError("That name has a blocked word in it: the repo never names the client")
    pack = project.Project(slug)
    with open(os.path.join(project.PLATFORM, "project_template.yml")) as fh:
        template = fh.read()
    body = template[template.index("name: __project__"):].replace("__project__", slug)
    files = {
        "project.yml": f"# {name}: in requirements. Made by `python -m ctl new-project`; the build\n"
                       "# logic - source systems, sample data, SQL, measure formulas - comes when\n"
                       "# the project is built (.claude/skills/build-from-requirements).\n"
                       f"name: {yaml.safe_dump(name).splitlines()[0]}\nslug: {slug}\n"
                       "# Source systems in use: none until it is built. Each needs a simulator\n"
                       "# (sources/simulators/) and a staging adapter (transform/platform/models/silver/staging/<system>/).\n"
                       "systems: []\nmdm_provider: splink\n"
                       "# The architecture version this project is built against (transform/platform).\n"
                       f"architecture: {platform_version()}\n"
                       "# Measure slots per dashboard row on the Requirements tab.\nslots: 4\n",
        "dbt_project.yml": "# Generated from transform/platform/project_template.yml: only `name` and\n"
                           "# `vars` may differ from it (python -m ctl check-pack).\n" + body,
        "packages.yml": "packages:\n  - local: ../../transform/platform\n  - package: dbt-labs/dbt_utils\n"
                        "    version: [\">=1.3.0\", \"<2.0.0\"]\n",
        "scenario.yml": "# The synthetic sources' settings (sources/generate.py reads them). Empty\n"
                        "# until the project has source systems: there is nothing to generate yet.\n{}\n",
        "backlog.yml": "# Measures the business asked for that have no formula yet. The Requirements\n"
                       "# tab adds them here; building one moves it to models/semantic/metrics.yml.\n#\n"
                       "#   placeholder   the data exists; the business has not defined the metric\n"
                       "#   blocked       the data does not exist in any source system\n\nmetrics: []\n",
        "golden_answers.yml": "# Golden answers: the acceptance test every semantic engine and BI tool must\n"
                              "# pass. None until a measure has a number; freeze them with\n"
                              "# `python -m evaluation.golden freeze` once the project is built.\n\n"
                              "version: 1\nas_of: null\ntolerance: 1.0e-06\nqueries: []\n",
        "models/semantic/metrics.yml": "# The metrics: each KPI's formula and its definition. Empty until the\n"
                                       "# first measure is built; until then they wait in backlog.yml.\n\nmetrics: []\n",
        "models/semantic/semantic_models.yml": "# Semantic models over the gold tables: written when the project is built.\n\n"
                                               "semantic_models: []\n",
        "models/semantic/saved_queries.yml": "# Saved queries: one per dashboard cube. Written when the project is built.\n\n"
                                             "saved_queries: []\n",
        "seeds/department.csv": "department_code,department_name,display_order\nUNASSIGNED,Unassigned,99\n",
        "seeds/process_metric.csv": "process_code,metric_name,slot,display_order\n",
        "seeds/department_metric.csv": "department_code,process_code,metric_name,influence\n",
        "docs/open_questions.md": f"# Open questions\n\nWhat {name}'s numbers will assume, and what reversing each costs.\n",
        **{f"requirements/{f}.yml": _comment(_HEADERS[f]) for f in requirements.FILES},
    }
    try:
        for rel, text in files.items():
            os.makedirs(os.path.dirname(pack.path(rel)), exist_ok=True)
            with open(pack.path(rel), "w") as fh:
                fh.write(text)
        requirements.regenerate(pack)
        problems = check(slug)
        if problems:
            raise ValueError("The new project doesn't pass check-pack: " + "; ".join(problems))
    except Exception:
        import shutil

        shutil.rmtree(pack.root, ignore_errors=True)
        raise
    return pack
