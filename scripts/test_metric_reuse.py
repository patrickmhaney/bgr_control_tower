"""Prove that one metric can serve two dashboards without being defined twice.

    python scripts/test_metric_reuse.py

This is the property the whole architecture turns on, and no current metric
exercises it - all seven defined metrics belong to exactly one process. So the
test creates the situation, measures what changed, and puts everything back.

What it does
------------
1. Records a hash of every metric definition and every generated metric model.
2. Adds one row to seeds/process_metric_map.csv mapping cost_per_shipment - an
   I2D metric - to O2C slot M4.
3. Regenerates and rebuilds.
4. Asserts:
     - no metric definition file changed
     - no generated metric SQL model changed
     - exactly one process view changed, mart_o2c
     - cost_per_shipment now appears on both dashboards
     - and returns bit-for-bit the same value on both
5. Restores the seed and rebuilds, leaving the project as it found it.

The last assertion is the one that matters. Two dashboards showing the same
metric name with different numbers is the failure this design exists to
prevent, and asserting equality is the only way to know it is prevented rather
than merely intended.
"""
import hashlib
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _toolchain import PYTHON, ROOT, dbt_command, project_env  # noqa: E402

SEED = os.path.join(ROOT, "seeds", "process_metric_map.csv")

REUSED_METRIC = "cost_per_shipment"
HOME_PROCESS = "I2D"
BORROWING_PROCESS = "O2C"
NEW_ROW = f"{BORROWING_PROCESS},{REUSED_METRIC},M4,4\n"

failures = []


def check(condition, message):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {message}")
    if not condition:
        failures.append(message)


def hash_tree(relative_dir, suffix):
    digests = {}
    directory = os.path.join(ROOT, relative_dir)
    for filename in sorted(os.listdir(directory)):
        if filename.endswith(suffix):
            path = os.path.join(directory, filename)
            digests[filename] = hashlib.sha256(open(path, "rb").read()).hexdigest()
    return digests


def run(cmd, **kwargs):
    result = subprocess.run(cmd, cwd=ROOT, env=project_env(),
                            capture_output=True, text=True, **kwargs)
    if result.returncode != 0:
        print(result.stdout[-4000:])
        print(result.stderr[-2000:], file=sys.stderr)
        raise SystemExit(f"command failed: {' '.join(cmd)}")
    return result.stdout


def rebuild():
    run([PYTHON, os.path.join("scripts", "generate_process_views.py")])
    run(dbt_command("seed", "--select", "process_metric_map", "--quiet"))
    run(dbt_command("run", "--select", "marts.process", "--quiet"))


def query(sql):
    import duckdb
    con = duckdb.connect(os.path.join(ROOT, "warehouse.duckdb"), read_only=True)
    try:
        return con.sql(sql).fetchall()
    finally:
        con.close()


def metric_value(process_code):
    rows = query(f"""
        select sum(numerator), sum(denominator),
               sum(numerator) / nullif(sum(denominator), 0)
        from main_process.mart_{process_code.lower()}
        where metric_name = '{REUSED_METRIC}'
    """)
    return rows[0] if rows else (None, None, None)


def main():
    original_seed = open(SEED).read()
    definitions_before = hash_tree("semantic/metrics", ".yml")
    metric_models_before = hash_tree("models/marts/metrics", ".sql")
    process_views_before = hash_tree("models/marts/process", ".sql")

    print(f"Reusing {REUSED_METRIC} ({HOME_PROCESS}) on {BORROWING_PROCESS} slot M4\n")

    try:
        with open(SEED, "a") as fh:
            fh.write(NEW_ROW)
        rebuild()

        definitions_after = hash_tree("semantic/metrics", ".yml")
        metric_models_after = hash_tree("models/marts/metrics", ".sql")
        process_views_after = hash_tree("models/marts/process", ".sql")

        check(definitions_before == definitions_after,
              "no metric definition changed - the metric is still defined exactly once")
        check(metric_models_before == metric_models_after,
              "no generated metric SQL model changed - no second implementation appeared")

        changed = {name for name in process_views_after
                   if process_views_before.get(name) != process_views_after[name]}
        check(changed == {f"mart_{BORROWING_PROCESS.lower()}.sql"},
              f"exactly one presentation view changed, and it is "
              f"mart_{BORROWING_PROCESS.lower()}.sql (changed: {sorted(changed) or 'none'})")

        home = metric_value(HOME_PROCESS)
        borrowed = metric_value(BORROWING_PROCESS)

        check(borrowed[1] is not None and borrowed[1] > 0,
              f"{REUSED_METRIC} now returns rows on {BORROWING_PROCESS}")
        check(home == borrowed,
              f"identical on both dashboards: {HOME_PROCESS} {home[2]} "
              f"vs {BORROWING_PROCESS} {borrowed[2]}")

        slots = query(f"""
            select process_code, slot from main_seed.process_metric_map
            where metric_name = '{REUSED_METRIC}' order by process_code
        """)
        check(len(slots) == 2,
              f"two map rows, one definition: {slots}")

    finally:
        with open(SEED, "w") as fh:
            fh.write(original_seed)
        rebuild()

    restored = metric_value(BORROWING_PROCESS)
    check(restored[1] is None,
          f"restored - {REUSED_METRIC} is off {BORROWING_PROCESS} again")
    check(hash_tree("models/marts/process", ".sql") == process_views_before,
          "project restored to its original state")

    print()
    if failures:
        print(f"FAILED: {len(failures)} assertion(s)")
        return 1
    print("All assertions passed. A metric can serve two dashboards from one definition.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
