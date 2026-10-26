"""The project pack in use, and where its content lives.

The architecture is the same for every project; what differs is a pack under
projects/<slug>/ (PLAN.md §6): its requirements content, its synthetic-data
settings and its SQL. Every module that reads content asks this module for
the path - nothing else builds one - so switching projects is one setting:

    python -m ctl --project sample ...     # or CT_PROJECT=sample
    from core.project import current; current().golden

The default is sample_v2, so `make setup mock run` needs no flag. Each
project also gets its own data directory (`{project}` in config/<env>.yaml).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import cached_property

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECTS = os.path.join(ROOT, "projects")
PLATFORM = os.path.join(ROOT, "transform", "platform")
DEFAULT = "sample_v2"

_active: str | None = None


def slug() -> str:
    return _active or os.environ.get("CT_PROJECT") or DEFAULT


def available() -> list[str]:
    return sorted(d for d in os.listdir(PROJECTS)
                  if os.path.isfile(os.path.join(PROJECTS, d, "project.yml")))


def use(name: str) -> Project:
    """Select a project for this process and the subprocesses it starts."""
    global _active
    if name not in available():
        raise SystemExit(f"unknown project {name!r}: expected one of {available()}")
    _active = name
    os.environ["CT_PROJECT"] = name
    return current()


def current() -> Project:
    return Project(slug())


@dataclass(frozen=True)
class Project:
    slug: str

    def path(self, *parts: str) -> str:
        return os.path.join(PROJECTS, self.slug, *parts)

    @property
    def root(self) -> str:
        return self.path()

    @cached_property
    def config(self) -> dict:
        """project.yml: name, systems in use, the MDM provider."""
        with open(self.path("project.yml")) as fh:
            return yaml.safe_load(fh)

    @property
    def name(self) -> str:
        return self.config.get("name", self.slug)

    @property
    def systems(self) -> list[str]:
        return list(self.config.get("systems") or [])

    # -- ingestion: contract C1 and C2 files
    @property
    def specs(self) -> str:
        return self.path("ingestion", "specs")

    @property
    def schemas(self) -> str:
        return self.path("ingestion", "schemas")

    @property
    def scenario(self) -> str:
        return self.path("scenario.yml")

    # -- dbt: the pack is a dbt project depending on transform/platform
    @property
    def dbt_dir(self) -> str:
        return self.root

    @property
    def models(self) -> str:
        return self.path("models")

    @property
    def seeds(self) -> str:
        return self.path("seeds")

    @property
    def semantic_dir(self) -> str:
        return self.path("models", "semantic")

    @property
    def target(self) -> str:
        return self.path("target")

    @property
    def manifest(self) -> str:
        return os.path.join(self.target, "manifest.json")

    @property
    def semantic_manifest(self) -> str:
        return os.path.join(self.target, "semantic_manifest.json")

    @cached_property
    def dbt_name(self) -> str:
        with open(self.path("dbt_project.yml")) as fh:
            return yaml.safe_load(fh)["name"]

    # -- governance, proof and generated files
    @property
    def backlog(self) -> str:
        return self.path("backlog.yml")

    @property
    def golden(self) -> str:
        return self.path("golden_answers.yml")

    @property
    def powerbi(self) -> str:
        return self.path("powerbi")

    @property
    def powerbi_model(self) -> str:
        return self.path("powerbi", "ControlTower.SemanticModel", "definition")

    @property
    def parity_queries(self) -> str:
        return self.path("powerbi", "parity", "parity_queries.json")

    @property
    def docs(self) -> str:
        return self.path("docs")
