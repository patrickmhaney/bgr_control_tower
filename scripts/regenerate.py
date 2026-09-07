"""Run every generator, in dependency order.

    python scripts/regenerate.py           # regenerate
    python scripts/regenerate.py --check   # fail if anything changed

Why this exists
---------------
About 70% of the SQL in this project is generated, and the generators have an
ordering dependency: editing a metric definition changes the compiled registry,
which changes the process views. Running one and not the next leaves a
generated file describing a definition that no longer exists.

That is not hypothetical - it happened. A metric's blocked_reason was edited,
`compile_metrics.py` was run, `generate_process_views.py` was not, and
`mart_s2p.sql` sat in the repo for a commit carrying the old text. Nothing
failed, because a stale generated file is still valid SQL.

`--check` is the CI job. It regenerates everything and fails if the working
tree moved, which makes "someone edited a definition and forgot to recompile"
a build failure instead of a slow-rotting inconsistency.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _toolchain import PYTHON, ROOT  # noqa: E402

# Order matters. compile_metrics writes the registry seed and the metric
# models that generate_process_views reads.
STEPS = [
    ("staging models", ["scripts/generate_staging.py"]),
    ("schema contract", ["scripts/freeze_schema_contract.py"]),
    ("metric artefacts", ["scripts/compile_metrics.py"]),
    ("process views", ["scripts/generate_process_views.py"]),
    # Reads the Mermaid out of docs/, so it is stale whenever a diagram is edited.
    ("diagram atlas", ["scripts/build_atlas.py", "docs/atlas.md"]),
]

#: These need a built warehouse, so they are not part of the default chain -
#: they run after `dbt build`. --with-exports includes them.
POST_BUILD = [
    ("build statistics", ["scripts/update_build_stats.py"]),
    ("metric parity (L3)", ["scripts/test_metric_parity.py", "--write-dax-gate"]),
    ("Power BI export", ["scripts/export_powerbi.py"]),
]


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                          text=True).stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true",
                        help="fail if regeneration changes any tracked file")
    parser.add_argument("--with-exports", action="store_true",
                        help="also run the post-build chain: build statistics, the "
                             "metric parity test and the Power BI export. Needs a "
                             "built warehouse.")
    args = parser.parse_args()

    before = git("status", "--porcelain")

    steps = STEPS + (POST_BUILD if args.with_exports else [])
    for label, command in steps:
        result = subprocess.run([PYTHON, *command], cwd=ROOT,
                                capture_output=True, text=True)
        if result.returncode != 0:
            print(result.stdout[-2000:])
            print(result.stderr[-2000:], file=sys.stderr)
            print(f"FAILED: {label}", file=sys.stderr)
            return 1
        print(f"  ok  {label}")

    # Build statistics live in the docs and are generated like everything else,
    # so a stale count is a build failure rather than something nobody notices.
    if args.check and os.path.exists(os.path.join(ROOT, "target", "run_results.json")):
        stats = subprocess.run(
            [PYTHON, "scripts/update_build_stats.py", "--check"],
            cwd=ROOT, capture_output=True, text=True)
        print(stats.stdout.strip() or stats.stderr.strip())
        if stats.returncode != 0:
            return 1

    after = git("status", "--porcelain")

    if not args.check:
        return 0

    changed = sorted(set(after.splitlines()) - set(before.splitlines()))
    if changed:
        print("\nRegeneration changed tracked files. A generated file in the repo "
              "does not match\nits definition - recompile and commit:\n")
        for line in changed:
            print(f"  {line}")
        return 1

    print("\nGeneration is a no-op: every generated file matches its definition.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
