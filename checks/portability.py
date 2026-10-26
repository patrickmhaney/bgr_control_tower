"""SQL portability check (rule 3 in PLAN.md §9.3): silver and gold must port.

    python -m checks.portability

Reads the compiled dbt project, then for every silver and gold model - the
pack's and the platform package's staging adapters:

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

from core import project

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


def _models() -> list[tuple[str, str, str]]:
    """(name shown, SQL as written, SQL as compiled) for every silver and gold model."""
    pack = project.current()
    compiled = os.path.join(pack.target, "compiled")
    roots = {pack.dbt_name: pack.models, "platform": os.path.join(project.PLATFORM, "models")}
    out = []
    for package, source in roots.items():
        base = os.path.join(compiled, package, "models")
        for layer in LAYERS:
            for f in glob.glob(os.path.join(base, layer, "**", "*.sql"), recursive=True):
                rel = os.path.relpath(f, base)
                if os.path.isfile(os.path.join(source, rel)):
                    out.append((rel, os.path.join(source, rel), f))
    return sorted(out)


def check() -> list[str]:
    problems = []
    files = _models()
    if not files:
        return ["no compiled SQL found - run `python -m ctl dbt compile` first"]
    for rel, source, path in files:
        written = _strip_comments(open(source).read())
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
