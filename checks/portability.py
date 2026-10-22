"""SQL portability check (rule 3 in PLAN.md §9.3): silver and gold must port.

    python -m checks.portability

Compiles the dbt project, then for every silver and gold model:

1. rejects constructs that lock the SQL to DuckDB (QUALIFY, EXCLUDE,
   GROUP BY ALL, :: casts, positional GROUP BY, USING joins, ...) in the SQL
   as written - macros such as dbt.datediff render per adapter, so they are
   judged by step 2;
2. transpiles the compiled SQL with sqlglot to T-SQL (Azure SQL, Fabric
   Warehouse) and to Snowflake, failing on anything sqlglot reports as
   unsupported.

It needs no adapter and no account. Bronze is exempt: it is the one layer
allowed engine-specific SQL, because another ingestion tool replaces it.
"""
from __future__ import annotations

import glob
import os
import re
import sys

import sqlglot

from core.settings import ROOT

COMPILED = os.path.join(ROOT, "transform", "target", "compiled", "control_tower", "models")
SOURCE = os.path.join(ROOT, "transform", "models")
LAYERS = ("silver", "gold")
TARGETS = ("tsql", "snowflake")

BANNED = {
    r"\bqualify\b": "QUALIFY (T-SQL has none)",
    r"\bexclude\s*\(": "SELECT * EXCLUDE",
    r"\bgroup\s+by\s+all\b": "GROUP BY ALL",
    r"::\s*[a-z]": ":: casts - use cast(... as ...)",
    r"\bgroup\s+by\s+\d": "positional GROUP BY - repeat the expressions",
    r"\bjoin\s+[\w.\"]+(?:\s+as\s+\w+)?\s+using\s*\(": "JOIN ... USING - use ON",
    r"\btry_strptime\b|\bstrftime\b|\blist_\w+\(|\bstruct_pack\b": "DuckDB-only function",
    r"\bilike\b": "ILIKE",
}


def _strip_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    return re.sub(r"--[^\n]*", " ", sql)


def check() -> list[str]:
    problems = []
    files = [f for layer in LAYERS
             for f in glob.glob(os.path.join(COMPILED, layer, "**", "*.sql"), recursive=True)
             if os.path.isfile(os.path.join(SOURCE, os.path.relpath(f, COMPILED)))]
    if not files:
        return ["no compiled SQL found - run `python -m ctl dbt compile` first"]
    for path in sorted(files):
        rel = os.path.relpath(path, COMPILED)
        written = _strip_comments(open(os.path.join(SOURCE, rel)).read())
        for pattern, why in BANNED.items():
            if re.search(pattern, written, flags=re.I):
                problems.append(f"{rel}: {why}")
        sql = _strip_comments(open(path).read())
        for dialect in TARGETS:
            try:
                sqlglot.transpile(sql, read="duckdb", write=dialect,
                                  unsupported_level=sqlglot.ErrorLevel.RAISE)
            except sqlglot.errors.SqlglotError as exc:
                problems.append(f"{rel}: does not translate to {dialect}: {str(exc).splitlines()[0]}")
    return problems


def main() -> None:
    problems = check()
    for p in problems:
        print(f"portability: {p}")
    print("portability: ok" if not problems else f"portability: {len(problems)} problem(s)")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
