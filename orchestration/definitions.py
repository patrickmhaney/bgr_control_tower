"""Dagster: one asset graph from source table to dashboard export.

    dagster dev -m orchestration.definitions        # or: make ui

Thin by rule (PLAN.md §9.3, rule 1): every asset calls the same step function
`python -m ctl` calls, and data quality checks live in dbt, so Dagster holds
no logic of its own. ADF, a Boomi Logic Flow, Snowflake Tasks or cron could
run the same steps.

    mock_clock  ->  <source>/<table>  ->  dbt (bronze, staging)  ->  mdm/<C3 table>
                ->  dbt (conformed, gold, tests)  ->  cubes (dashboard_cube for Power BI)
                ->  serving load, warehouse publish

Alerts: a failed run posts to CT_ALERT_WEBHOOK (a Teams or Slack incoming
webhook) when it is set.
"""

import json
import os
import sys
import urllib.request

import dagster as dg
from dagster_dbt import DagsterDbtTranslator, DbtCliResource, DbtProject, dbt_assets

from core import project
from core.settings import settings

os.environ.update(settings.dbt_env())

PROJECT = DbtProject(project_dir=project.current().dbt_dir)
PRE_MDM = "tag:bronze tag:staging resource_type:seed"
SOURCES = tuple(project.current().systems)
MDM_TABLES = ("mdm_xref", "mdm_golden_customer", "mdm_golden_employee")
MDM_INPUTS = [["silver", m] for m in ("stg_sage_x3__bpcustomer", "stg_hubspot__company",
                                       "stg_sage_x3__autilis", "stg_hubspot__owner",
                                       "stg_sage_x3__represent")] + [["seed", "legal_suffix"]]


class Translator(DagsterDbtTranslator):
    """dbt sources keep their default keys, [source, table], which the extract
    and MDM assets below produce - so lineage runs from each source table."""


# --------------------------------------------------------------- sources --
@dg.asset(group_name="sources", description="Moves the synthetic sources forward one day (mock mode only).")
def mock_clock(context: dg.AssetExecutionContext) -> dg.MaterializeResult:
    from sources import clock

    if settings.source_mode != "mock":
        return dg.MaterializeResult(metadata={"skipped": "live sources"})
    if not os.path.exists(settings.mock_db):
        clock.init()
    else:
        clock.advance(1)
    return dg.MaterializeResult(metadata={"today": str(clock.status()["today"])})


def _bronze_asset(source: str):
    from ingestion.sources import load_spec

    tables = list(load_spec(source).tables)

    @dg.multi_asset(name=f"extract_{source}", group_name="ingestion",
                    specs=[dg.AssetSpec([source, t], deps=[mock_clock]) for t in tables],
                    description=f"Extract {source} into the bronze changelog (contracts C1, C2).",
                    config_schema={"full_refresh": dg.Field(bool, default_value=False),
                                   "reconcile": dg.Field(bool, default_value=False)})
    def _asset(context: dg.AssetExecutionContext):
        from ingestion.run import extract

        counts = extract(source, full_refresh=context.op_config["full_refresh"],
                         reconcile=context.op_config["reconcile"])
        for t in tables:
            yield dg.MaterializeResult(asset_key=[source, t], metadata={"rows": counts.get(t, 0)})
    return _asset


bronze_assets = [_bronze_asset(s) for s in SOURCES]


# ------------------------------------------------------------------- dbt --
@dbt_assets(manifest=PROJECT.manifest_path, select=PRE_MDM, name="dbt_before_mdm",
            dagster_dbt_translator=Translator(), project=PROJECT)
def dbt_before_mdm(context: dg.AssetExecutionContext, dbt: DbtCliResource):
    # Cautious: tests that also touch post-MDM models run in dbt_after_mdm.
    yield from dbt.cli(["build", "--indirect-selection", "cautious"], context=context).stream()


@dg.multi_asset(name="mdm_contract_c3", group_name="mdm",
                specs=[dg.AssetSpec(["mdm", t], deps=[dg.AssetKey(k) for k in MDM_INPUTS])
                       for t in MDM_TABLES],
                description="Run the MDM provider and land contract C3 (Splink or rules).")
def mdm_contract_c3():
    from mdm.run import run_mdm

    quality = run_mdm()
    c = quality.get("customer") or {}
    meta = {"provider": quality["provider"], "needs_review": quality["needs_review"],
            "precision": c.get("precision"), "recall": c.get("recall")}
    for t in MDM_TABLES:
        yield dg.MaterializeResult(asset_key=["mdm", t], metadata=meta)


@dbt_assets(manifest=PROJECT.manifest_path, select="fqn:*", exclude=PRE_MDM,
            name="dbt_after_mdm", dagster_dbt_translator=Translator(), project=PROJECT)
def dbt_after_mdm(context: dg.AssetExecutionContext, dbt: DbtCliResource):
    yield from dbt.cli(["build"], context=context).stream()


def _gold() -> list[dg.AssetKey]:
    """Every gold model in the pack: the cubes read from them."""
    with open(PROJECT.manifest_path) as fh:
        nodes = json.load(fh)["nodes"].values()
    return [dg.AssetKey(["gold", n["name"]]) for n in nodes
            if n["resource_type"] == "model" and n["config"].get("schema") == "gold"]


GOLD = _gold()


# --------------------------------------------------------------- serving --
@dg.asset(group_name="serving", deps=GOLD,
          description="Materialise the MetricFlow saved queries as cubes, stacked into dashboard_cube.")
def marts() -> dg.MaterializeResult:
    from serving.materialize import materialize

    return dg.MaterializeResult(metadata=materialize())


@dg.asset(group_name="serving", deps=[marts],
          description="Reverse-load the marts into the serving database (contract C7).")
def serving_db() -> dg.MaterializeResult:
    from serving.reverse_load import load_serving

    return dg.MaterializeResult(metadata=load_serving())


@dg.asset(group_name="serving", deps=[marts],
          description="Publish the warehouse file to raw storage for read-only consumers.")
def warehouse_publish() -> dg.MaterializeResult:
    from serving.publish import publish_warehouse

    return dg.MaterializeResult(metadata={"published_to": publish_warehouse()})


# ---------------------------------------------------------- jobs, alerts --
daily = dg.define_asset_job("daily", selection=dg.AssetSelection.all())
jobs, schedules = [daily], [dg.ScheduleDefinition(job=daily, cron_schedule="0 6 * * *")]
if "hubspot" in SOURCES:
    weekly_reconcile = dg.define_asset_job(
        "weekly_reconcile", selection=dg.AssetSelection.groups("ingestion") & dg.AssetSelection.key_prefixes("hubspot"),
        config={"ops": {"extract_hubspot": {"config": {"reconcile": True}}}},
        description="Diff HubSpot keys against the source to catch hard deletes.")
    jobs.append(weekly_reconcile)
    schedules.append(dg.ScheduleDefinition(job=weekly_reconcile, cron_schedule="0 5 * * 0"))
if "sage_x3" in SOURCES:
    jobs.append(dg.define_asset_job(
        "cdc_resnapshot", selection=dg.AssetSelection.groups("ingestion") & dg.AssetSelection.key_prefixes("sage_x3"),
        config={"ops": {"extract_sage_x3": {"config": {"full_refresh": True}}}},
        description="Snapshot X3 again. Runs by itself when CDC retention was exceeded."))


@dg.run_failure_sensor(description="Post failed runs to CT_ALERT_WEBHOOK.")
def alert_on_failure(context: dg.RunFailureSensorContext):
    url = os.environ.get("CT_ALERT_WEBHOOK")
    if not url:
        return
    text = (f"Control Tower ({settings.env}): run {context.dagster_run.job_name} failed - "
            f"{context.failure_event.message}")
    req = urllib.request.Request(url, data=json.dumps({"text": text}).encode(),
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=10)


defs = dg.Definitions(
    assets=[mock_clock, *bronze_assets, dbt_before_mdm, mdm_contract_c3, dbt_after_mdm,
            marts, serving_db, warehouse_publish],
    jobs=jobs,
    schedules=schedules,
    sensors=[alert_on_failure],
    resources={"dbt": DbtCliResource(
        project_dir=PROJECT,
        # The dbt next to this interpreter, so a virtualenv need not be on PATH.
        dbt_executable=os.path.join(os.path.dirname(sys.executable), "dbt"))},
)
