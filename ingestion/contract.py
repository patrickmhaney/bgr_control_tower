"""The pinned source schema, and drift detection against it.

Loaded by every resource so dlt is told what to expect rather than left to
infer it from whatever rows happen to arrive. See
scripts/freeze_schema_contract.py for why that matters.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTRACT_PATH = os.path.join(ROOT, "ingestion", "schema_contract.json")

_contract: dict | None = None


def contract() -> dict:
    global _contract
    if _contract is None:
        if not os.path.exists(CONTRACT_PATH):
            raise FileNotFoundError(
                f"{CONTRACT_PATH} is missing. Run "
                f"`python scripts/freeze_schema_contract.py` once, "
                f"review the output, and commit it."
            )
        with open(CONTRACT_PATH) as fh:
            _contract = json.load(fh)
    return _contract


def columns_for(source: str, table: str) -> dict | None:
    """dlt column hints for a table, or None if the table is not under contract."""
    return contract().get(source, {}).get(table)


@dataclass(frozen=True)
class Drift:
    source: str
    table: str
    missing: tuple[str, ...]
    added: tuple[str, ...]

    @property
    def is_incident(self) -> bool:
        """A lost column breaks something downstream. A new one does not."""
        return bool(self.missing)

    def describe(self) -> str:
        parts = []
        if self.missing:
            parts.append(f"LOST {', '.join(self.missing)}")
        if self.added:
            parts.append(f"new {', '.join(self.added)}")
        return f"{self.source}.{self.table}: " + "; ".join(parts)


def check(source: str, table: str, observed: list[str]) -> Drift | None:
    expected = columns_for(source, table)
    if expected is None:
        return None
    observed_set = set(observed)
    missing = tuple(c for c in expected if c not in observed_set)
    added = tuple(c for c in observed if c not in expected)
    if not missing and not added:
        return None
    return Drift(source, table, missing, added)
