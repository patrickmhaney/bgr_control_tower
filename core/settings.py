"""Environment settings: `PLATFORM_ENV` picks `config/<env>.yaml`.

Every component reads its locations from here, so moving from a laptop to
Azure is a change of environment, not of code. Any key can be overridden by an
environment variable named `CT_<KEY>` (upper case), which is how secrets and
per-run values reach a container without touching the YAML. A `{project}` in
a path is the project pack in use (core/project.py), so each project gets its
own data directory.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import cached_property

import yaml

from core import project

ROOT = project.ROOT


def _resolve(value: str) -> str:
    """Relative paths are relative to the repo root; URLs pass through."""
    value = value.replace("{project}", project.slug())
    if "://" in value or os.path.isabs(value):
        return value
    return os.path.join(ROOT, value)


@dataclass
class Settings:
    env: str

    @cached_property
    def raw(self) -> dict:
        path = os.path.join(ROOT, "config", f"{self.env}.yaml")
        with open(path) as fh:
            return yaml.safe_load(fh)

    def get(self, key: str, default=None):
        return os.environ.get(f"CT_{key.upper()}", self.raw.get(key, default))

    @property
    def data_dir(self) -> str:
        return _resolve(self.get("data_dir", ".data"))

    @property
    def mock_db(self) -> str:
        return _resolve(self.get("mock_db", ".data/mock_sources.duckdb"))

    @property
    def bronze_root(self) -> str:
        return _resolve(self.get("bronze_root", ".data/bronze"))

    @property
    def warehouse_path(self) -> str:
        return _resolve(self.get("warehouse_path", ".data/warehouse.duckdb"))

    @property
    def exports_root(self) -> str:
        return _resolve(self.get("exports_root", ".data/exports"))

    @property
    def serving_destination(self) -> str:
        return self.get("serving_destination", "duckdb")

    @property
    def serving_url(self) -> str:
        url = self.get("serving_url", ".data/serving.duckdb")
        return url.replace("{project}", project.slug()) if self.serving_destination != "duckdb" else _resolve(url)

    @property
    def mdm_provider(self) -> str:
        default = project.current().config.get("mdm_provider") or self.raw.get("mdm_provider", "splink")
        return os.environ.get("CT_MDM_PROVIDER", default)

    @property
    def source_mode(self) -> str:
        return self.get("source_mode", "mock")

    @property
    def dbt_target(self) -> str:
        return self.get("dbt_target", self.env)

    def dbt_env(self) -> dict[str, str]:
        """Environment variables profiles.yml and dbt_project.yml read."""
        return {
            "DBT_PROFILES_DIR": os.path.join(ROOT, "transform"),
            "CT_SYSTEMS": ",".join(project.current().systems),
            "CT_WAREHOUSE_PATH": self.warehouse_path,
            "CT_BRONZE_ROOT": self.bronze_root,
            "CT_DBT_TARGET": self.dbt_target,
        }


settings = Settings(env=os.environ.get("PLATFORM_ENV", "local"))
