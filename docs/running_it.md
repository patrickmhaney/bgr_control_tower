# Running it

A working reference. Every command here was run against this repo; the output
shown is real.

Everything is read-only against the source database, everything is
reproducible, and `--reset` is safe — the whole warehouse can be rebuilt from
the source systems in about fifteen seconds.

## Setup

Python 3.9–3.12; 3.11 is what this was built and verified on.

```bash
git clone <repo> bgr_control_tower && cd bgr_control_tower

python3 -m venv .venv
source .venv/bin/activate                  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

dbt deps                              # installs dbt_utils
```

Two environment variables. Neither has a sensible default dbt can infer, and
the second one is the difference between working and quietly writing databases
into the wrong directory:

```bash
export DBT_PROFILES_DIR="$PWD"            # where profiles.yml lives
export BGR_CONTROL_TOWER_HOME="$PWD"      # where the DuckDB files live
```

```powershell
# Windows PowerShell
$env:DBT_PROFILES_DIR = $PWD
$env:BGR_CONTROL_TOWER_HOME = $PWD
```

`BGR_CONTROL_TOWER_HOME` defaults to `.`, so you can skip it **if you always run
from the project root**. A scheduler, a CI job or anything using
`--project-dir` runs from somewhere else, and without it dbt creates a stray
`warehouse.duckdb` in its working directory and then fails to find `raw.duckdb`.
Set both in your shell profile and stop thinking about it.

Every command below assumes the environment is activated, so `python` and `dbt`
are this project's. If you would rather not activate, prefix them —
`.venv/bin/python`, or `.venv\Scripts\python.exe` on Windows.

The source data ships with the repo as `mock_sources.duckdb`. Nothing else has
to exist before the first run.

To regenerate or rescale it — the `SCALE` block at the top of
`generate_mock_sources.py` controls volumes — you need one extra dependency:

```bash
pip install -r requirements-dev.txt
python generate_mock_sources.py            # writes next to the script
MOCK_SOURCES_DIR=/tmp/scratch python generate_mock_sources.py   # or elsewhere
```

It is seeded, so the *data* reproduces exactly unless you change `SCALE`. The
DuckDB **file** does not: rewriting it produces a different byte stream from
identical rows, so `mock_sources.duckdb` shows as modified in git after every
regeneration. `git checkout -- mock_sources.duckdb` if you did not mean to
change the data.

---

## The 30-second version

```bash
python run_ingestion.py     # source systems -> landing -> raw
dbt build                   # raw -> models, tests, snapshots
python scripts/q.py --ls    # what you can now query
python scripts/q.py         # interactive SQL
```

Starting from nothing, or want a guaranteed-clean state? See
[Reset to an empty baseline and rebuild](#reset-to-an-empty-baseline-and-rebuild).

---

## 1. The pipeline

### Look before you run

```bash
python run_ingestion.py --explain
```

Prints the extraction spec for all 54 tables: strategy, write disposition,
primary key, and a note on each saying why. This is the fastest way to see what
the extraction design actually commits to, and it is the thing to walk a client
through.

### Run it

```bash
python run_ingestion.py                 # all five sources
python run_ingestion.py sage_x3 hubspot # named sources
python run_ingestion.py --full-refresh  # ignore watermarks
python run_ingestion.py --reset         # wipe archive, raw db, state
```

A second run of `sage_x3` alone:

```
source        tables   rows read   seconds
-------------------------------------------
sage_x3           30      13,296       0.9

projecting landing -> raw
  raw.sage_x3      30 tables     94,075 rows

schema contract
  no drift - every table matches ingestion/schema_contract.json
```

**Read those two numbers together.** 13,296 rows were *read* from the ERP;
94,075 are *in* raw. The difference is the incremental window doing its job —
merge disposition keeps the rows a windowed run did not revisit.

### See why a run read what it read

```bash
python run_ingestion.py --state
```

Every stored watermark, which tables have none, and the size of the landing
archive. When an incremental extract returns more or fewer rows than you
expected, this is the first place to look.

```
watermarks  (17 stored)
  sage_x3      SORDER           2026-09-29   minus 90d lookback
  ...
sources with no watermark - these read everything, every run
  paycom        6 of  6 tables   employee, check, earning_detail, ...
  netstock      5 of  5 tables   item_location, forecast, ...
```

### Reset and watch the difference

```bash
python run_ingestion.py --reset
python run_ingestion.py     # 247,851 rows - full backfill
python run_ingestion.py     # 126,399 rows - watermarks now set
```

`--reset` clears the ingestion layer only: `landing/`, `raw.duckdb` and
`ingestion/_state`. It leaves `warehouse.duckdb`, `target/` and `exports/`
alone. For a true empty baseline see the section below.

### Reset to an empty baseline and rebuild

Everything in this project is derived. Nothing below is precious and all of it
regenerates in about fifteen seconds, which is what makes a full teardown the
right first move when something looks wrong.

```bash
# 1. Clear everything derived
python run_ingestion.py --reset          # landing/, raw.duckdb, ingestion/_state
rm -rf warehouse.duckdb target exports   # dbt output, dbt artefacts, exports

# 2. Rebuild
python generate_mock_sources.py          # optional - mock_sources.duckdb, 247,851 rows
python run_ingestion.py                  # -> landing/ -> raw.duckdb
dbt build                                # raw -> every model, test and snapshot

# 3. Rebuild exports/
python scripts/compile_metrics.py                     # metric registry for ask_metric.py
python scripts/test_metric_parity.py --write-dax-gate # needs the warehouse
python scripts/export_powerbi.py                      # needs the warehouse
```

Step 3 is also what `python scripts/regenerate.py --with-exports` runs, after
re-running the other generators (a no-op when nothing changed).

Expected:

```
raw          247,851 rows across 5 schemas
dbt build    PASS=... WARN=4 ERROR=0
parity       every re-aggregatable metric reconciles
export       14 tables, 22 relationships, 10 generated measures, 0 hand-written
```

The four warnings are the documented dashed-line relationships - duplicate
Paycom emails, orphaned Netstock item-locations, Pangea customer POs that match
nothing in X3, Paycom GL accounts that do not exist in X3. They are supposed to
warn. See "Data quality" in [architecture.md](architecture.md).

Step 1 is only needed for a genuine clean slate. Day to day, `dbt build` alone
is enough - it is idempotent, and `run_ingestion.py` is only needed when the
source data changed.

**One ordering trap.** Seeds are tables, so a change to `+column_types` in
`dbt_project.yml` does not reach an existing warehouse. Run
`dbt seed --full-refresh` once after changing one. A clean rebuild does not
need this, because the seed is created fresh.

---

## 2. Stepping through the pipeline

### Drive a simulator directly

The fastest way to understand what an extractor sees. Each simulator is the
stand-in for one real source system.

```bash
python -c "
from ingestion.simulators import erp_database as erp
import datetime as dt
print('full          ', len(erp.read_full('SORDERQ')))
print('windowed 2026 ', len(erp.read_header_window('SORDERQ','SORDER','SOHNUM_0','ORDDAT_0', dt.date(2026,1,1))))
"
```

```
full           11575
windowed 2026  4196
```

The HubSpot client is the one worth poking at — it demonstrates the archived
pass and counts its own API calls:

```bash
python -c "
from ingestion.simulators.hubspot_api import HubSpotClient
c = HubSpotClient(); rows = list(c.list_objects('company', order_by=['id']))
print(len(rows), 'rows in', c.requests_made, 'requests')
c2 = HubSpotClient(); print(len(list(c2.list_objects('company', include_archived=False, order_by=['id']))), 'without the archived pass')
"
```

```
260 rows in 4 requests
248 without the archived pass          # 12 silently lost
```

### Query the landing archive directly

The archive is plain Parquet on disk. No database needed:

```bash
python scripts/q.py "
  select load_date, count(*) as rows, count(distinct _dlt_load_id) as load_packages
  from read_parquet('landing/sage_x3/SORDER/**/*.parquet', hive_partitioning => true)
  group by 1 order by 1"
```

```bash
ls landing/sage_x3/SORDERQ/                 # one directory per table
ls landing/_incoming/paycom/                # the simulated SFTP drop
```

### Trace one table across the whole pipeline

The single most useful debugging query in the project:

```bash
python scripts/q.py "
  select (select count(*) from mock_sources.pangea.shipment)                         as at_source,
         (select count(*) from read_parquet('landing/pangea/shipment/**/*.parquet')) as in_archive,
         (select count(*) from raw.pangea.shipment)                                  as landed,
         (select count(*) from stg_pangea__shipment)                                 as staged,
         (select count(*) from fct_shipment)                                         as modelled"
```

```
  at_source  in_archive  landed  staged  modelled
  ---------  ----------  ------  ------  --------
  3509       3509        3509    3509    3509
```

When a number drops between two of those columns, you know exactly which layer
to open.

---

## 3. dbt

### Build

```bash
dbt build                            # everything: models + tests, in order
dbt run                              # models only
dbt test                             # tests only
dbt build --select marts.core        # one layer
dbt build --select fct_shipment      # one model
```

Expect `ERROR=0` and four warnings. **The four warnings are the point**, not a
problem — they are the documented dashed lines in the join map, each with a
threshold.

### Selectors — this is where dbt earns its keep

```bash
dbt build --select +mtr_on_time_delivery_rate   # it and everything upstream
dbt build --select fct_shipment+                # it and everything downstream
dbt build --select +fct_shipment+               # both directions
dbt build --select state:modified+              # only what changed (needs a stored manifest)
```

```bash
dbt ls --select +mtr_on_time_delivery_rate --resource-type model
```

```
stg_pangea__shipment  stg_pangea__charge  stg_pangea__tracking_event
stg_sage_x3__sorder   stg_sage_x3__sorderq  stg_sage_x3__bpcustomer  stg_sage_x3__aplstd
int_shipment_charge   int_shipment_milestone  int_shipment_order
fct_shipment          mtr_on_time_delivery_rate
```

### Inspect without materialising

```bash
dbt show --select int_shipment_charge --limit 3
dbt show --inline "select * from {{ ref('fct_shipment') }} limit 5"
dbt compile --select mtr_cost_per_order    # see the SQL dbt generates
```

`dbt show --inline` is the one to remember: it runs arbitrary SQL with `ref()`
and `source()` resolved, which is how you test a join before writing a model.

### Prove ingestion changed nothing

```bash
dbt build --vars '{source_database: mock_sources}'   # bypass the pipeline
python scripts/verify_ingestion.py                   # build both ways and diff
```

```
[PASS] core model row counts identical (56,998 rows across 11 models)
[PASS] on_time_delivery_rate            0.755989 == 0.755989
```

### Docs and lineage

```bash
dbt docs generate && dbt docs serve
```

The interactive DAG. Click any model for its lineage, its columns, its tests
and its compiled SQL. `dbt docs generate` also writes `target/catalog.json`,
which lets `compile_metrics.py` check that every column a metric names exists.

---

## 4. Querying the result

### The query tool

```bash
python scripts/q.py                    # interactive prompt
python scripts/q.py "select 1"         # one-shot
python scripts/q.py --ls               # everything queryable
python scripts/q.py --ls shipment      # filtered
python scripts/q.py -d fct_shipment    # columns, types, row count
python scripts/q.py --csv "..." > out.csv
```

Three databases are attached read-only under stable names, so one query can
join across the whole pipeline:

| name | what it holds |
|---|---|
| `mock_sources` | the source systems |
| `raw` | what ingestion landed |
| `warehouse` | what dbt built — the default, no prefix needed |

Unqualified names resolve across every dbt layer, so `fct_shipment`,
`mtr_cost_per_shipment`, `mart_i2d` and `stg_pangea__charge` all just work.

In the prompt: `\l` lists objects, `\d <table>` describes one, `\q` quits, and
statements end with `;`.

### Where things live

| Schema | What | Materialised as |
|---|---|---|
| `main_staging` | 54 models, 1:1 with source tables | views |
| `main_intermediate` | 10 crosswalk, entity-resolution and matching models | mixed |
| `main_core` | 5 dims + 6 facts — **the data model** | tables |
| `main_metrics` | 10 generated metric models | views |
| `main_process` | 9 dashboard views | views |
| `main_seed` | process map, site crosswalk, metric registry, legal suffixes | tables |
| `snapshot` | Type 2 history, accumulating. Nothing reads it yet | tables |

### Queries worth starting from

```sql
-- the shipment fact, sliced
select site_code, count(*) as shipments,
       round(100.0 * count(*) filter (where is_on_time_vs_carrier_promise)
             / count(*) filter (where is_on_time_vs_carrier_promise is not null), 1) as otd_pct,
       round(avg(shipment_cost_usd), 2) as avg_cost
from fct_shipment group by 1 order by 1;

-- a metric, rolled up. Always sum numerator and denominator separately -
-- averaging metric_value is wrong.
select round(100.0 * sum(numerator) / sum(denominator), 1) as otd
from mtr_on_time_delivery_rate;

-- a dashboard: one row per tile
select slot, metric_label, metric_status,
       round(sum(numerator) / nullif(sum(denominator), 0), 4) as value
from mart_i2d group by 1, 2, 3 order by 1;

-- entity resolution, published rather than buried
select source_scope, count(*),
       count(*) filter (where match_is_ambiguous) as ambiguous
from dim_customer group by 1;

-- reconciliation: invoice lines vs the general ledger
select (select round(sum(line_net_amount_usd), 0) from fct_invoice_line)      as invoiced,
       (select round(sum(amount_company_currency), 0) from stg_sage_x3__gaccentryd
        where gl_account_code = '41000')                                       as gl_revenue;
```

### Ask for a metric by name

`ask_metric.py` reads `exports/semantic/metric_registry.json`, which
`python scripts/compile_metrics.py` writes. Run that once first if `exports/`
is empty.

```bash
python scripts/ask_metric.py --list
python scripts/ask_metric.py on_time_delivery_rate --describe
python scripts/ask_metric.py on_time_delivery_rate --where site.city=Reno --period 2026-Q2
python scripts/ask_metric.py on_time_delivery_rate --by carrier.carrier_name --sql
python scripts/ask_metric.py dso_days_to_pay_proxy   # provisional: the caveats travel with the number
```

```
On-Time Delivery (active)

         74.3%    (n = 218)

  CAVEAT: The 128 undelivered shipments (109 EXCEPTION, 19 IN_TRANSIT) are
    excluded from the denominator, ...
```

It writes its own SQL from the registry. `--sql` shows what it generated,
which is a good way to learn the metric models.

---

## 5. Changing things

### Add or edit a metric

1. Edit or add a file in `semantic/metrics/`.
2. Add a row to `seeds/process_metric_map.csv` to put it on a dashboard.
3. `python scripts/regenerate.py && dbt build`
4. `python scripts/export_powerbi.py` to put the measure in the Power BI model.

`scripts/regenerate.py --check` fails if any generated file is out of step with
its definition. Run it before committing.

### Flip a documented assumption

Most open questions are a var or a one-line metric edit. Either way it is a
rebuild, not a remodel:

```bash
dbt build --vars '{shipment_cost_basis: shipment_header}'
dbt build --vars '{fiscal_year_start_month: 7}'
```

On-Time Delivery's promise basis lives in the metric definition instead:
`fct_shipment` carries both flags, so pointing
`semantic/metrics/on_time_delivery_rate.yml` at
`is_on_time_vs_customer_request` and running `python scripts/regenerate.py &&
dbt build` moves it from 75.6% to 84.1%.

### Regenerate everything

```bash
python scripts/regenerate.py                  # staging, contract, metrics, process views
python scripts/regenerate.py --with-exports   # + parity test and Power BI export
```

`--with-exports` needs a built warehouse. Its two post-build steps reconcile
every metric between its pre-aggregated model and its base fact, and regenerate
the Parquet and the Power BI model.

### Check the metrics agree with themselves

```bash
python scripts/test_metric_parity.py                    # metric model vs base fact
python scripts/test_metric_parity.py --write-dax-gate   # + the DAX queries for Power BI
```

One definition is rendered twice — SQL for the warehouse, DAX for Power BI —
and nothing but this asserts they agree. It is how a 17.3% divergence between
the warehouse and the DAX on Cost Per Order was caught and fixed. Run it after
any change to a metric definition.

### Snapshots

```bash
dbt snapshot                            # accumulate Type 2 history
python scripts/q.py "select * from snap_bpcustomer limit 5"
```

Three snapshots run and nothing consumes them. That is deliberate: a Type 2
dimension can only be built forward from its first snapshot and no source
carries effective dating, so this is the one decision that gets more expensive
the longer it stays open. See open question 11.

`dbt build` runs them too. On their own, run `dbt snapshot` **after** a build:
the snapshots read staging models, which are views — on a cold warehouse they
do not exist yet and `dbt snapshot` fails.

---

## 6. Running it unattended

Nothing here needs a working directory, a shell profile or an activated
environment — everything resolves from paths, provided the two variables are
set. A cron entry or CI step is one block:

```bash
#!/usr/bin/env bash
set -euo pipefail

export BGR_CONTROL_TOWER_HOME=/srv/bgr_control_tower
export DBT_PROFILES_DIR="$BGR_CONTROL_TOWER_HOME"
PY="$BGR_CONTROL_TOWER_HOME/.venv/bin/python"

"$PY" "$BGR_CONTROL_TOWER_HOME/run_ingestion.py"
"$PY" -m dbt.cli.main build    --project-dir "$BGR_CONTROL_TOWER_HOME"
"$PY" "$BGR_CONTROL_TOWER_HOME/scripts/test_metric_parity.py"
"$PY" "$BGR_CONTROL_TOWER_HOME/scripts/export_powerbi.py"
```

`python -m dbt.cli.main` rather than the `dbt` console script: it works
regardless of whether the environment is activated or the script is on PATH,
which is exactly the condition a scheduler runs under. `dbt build` includes the
snapshots.

**What to alert on**, in priority order:

| Signal | Meaning |
|---|---|
| Non-zero exit from `run_ingestion.py` | extraction failed, or a schema-contract **INCIDENT** — a source lost a column |
| Non-zero exit from `dbt build` | a test failed at `error` severity. The four `warn` tests do not affect exit status |
| A stale Paycom export | `read_latest()` raises rather than loading it. A missing file is indistinguishable from an unchanged one |
| Non-zero exit from `test_metric_parity.py` | a metric no longer reconciles between its pre-aggregated model and its base fact — a compiler or modelling bug, not a data one |
| Snapshots skipped | history stops accumulating, and it cannot be backfilled |
| `rows read` far from its usual value | a watermark reset, or a source stopped changing. `run_ingestion.py --state` tells you which |

The landing archive grows forever by design, so give it a retention policy
before it becomes someone's disk-space incident.

For CI, add the regeneration guard. It catches a metric definition edited
without recompiling — otherwise invisible, because a stale generated file is
still valid SQL:

```bash
python scripts/regenerate.py --check
python scripts/test_metric_parity.py       # after `dbt build`
```

---

## 7. When something breaks

| Symptom | Cause | Fix |
|---|---|---|
| `Catalog "raw" does not exist` | ingestion has not run | `run_ingestion.py` |
| `Catalog "mock_sources" does not exist` | connecting to `warehouse.duckdb` directly | use `scripts/q.py`, which attaches all three |
| dbt `Could not find profile` | `DBT_PROFILES_DIR` unset | `export DBT_PROFILES_DIR="$PWD"` |
| A stray `warehouse.duckdb` appears in your working directory | ran dbt from outside the project root without `BGR_CONTROL_TOWER_HOME` | `export BGR_CONTROL_TOWER_HOME=/path/to/bgr_control_tower` |
| `Cannot open database ".../raw.duckdb" in read-only mode` | same cause | same fix, then `python run_ingestion.py` |
| `database is locked` | dbt or ingestion is running | wait; DuckDB allows one writer |
| `No compiled registry` from `ask_metric.py` | `exports/` is empty | `python scripts/compile_metrics.py` |
| Drift reported as **INCIDENT** | a source lost a column | find out why. **Never** regenerate the contract to silence it |
| A test fails after editing a model | usually a real grain or relationship break | `dbt build --select <model>` then read the failing test's compiled SQL in `target/` |
| Numbers changed and you do not know why | | `scripts/verify_ingestion.py` isolates ingestion from modelling |

When in doubt, run the [full teardown](#reset-to-an-empty-baseline-and-rebuild).
The source systems are the only thing in this project that cannot be rebuilt.
