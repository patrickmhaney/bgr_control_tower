"""Locate this project's Python and dbt without assuming how it was installed.

Scripts that shell out to dbt or to another script used to hardcode the
literal path `.venv/bin/python`, which assumes a virtualenv, assumes it is
called `.venv`, and assumes POSIX layout. All three are wrong somewhere: Windows puts
executables in `Scripts/`, CI images often install into the system interpreter,
and plenty of people name their environment something else.

`sys.executable` is always the interpreter currently running, so it is the
right answer on every platform and every install layout.
"""
from __future__ import annotations

import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: The interpreter running this script. Correct by construction.
PYTHON = sys.executable


def dbt_command(*args: str) -> list[str]:
    """Build a dbt invocation that works wherever dbt actually lives.

    Prefers the console script next to the current interpreter, then one on
    PATH, then the module entry point - which always works if dbt is importable
    at all, and is the fallback that makes this safe in a container.
    """
    bindir = os.path.dirname(PYTHON)
    for candidate in ("dbt", "dbt.exe"):
        path = os.path.join(bindir, candidate)
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return [path, *args]
    found = shutil.which("dbt")
    if found:
        return [found, *args]
    return [PYTHON, "-m", "dbt.cli.main", *args]


def project_env(**overrides: str) -> dict:
    """Environment for a subprocess that has to find this project.

    dbt resolves `profiles.yml` from DBT_PROFILES_DIR, and profiles.yml
    resolves the DuckDB files from BGR_CONTROL_TOWER_HOME. Without the second one,
    running dbt from any directory other than the project root creates a stray
    `warehouse.duckdb` in the working directory and fails to find `raw.duckdb`.
    """
    return dict(
        os.environ,
        DBT_PROFILES_DIR=ROOT,
        BGR_CONTROL_TOWER_HOME=ROOT,
        **overrides,
    )
