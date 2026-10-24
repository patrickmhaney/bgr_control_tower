"""Ask the metrics: an app with embedded AI that can only reach governed metrics.

    uv sync --extra examples
    python -m apps.examples.ask_metrics.app "Which site had the worst on-time delivery last quarter?"

Claude answers by calling four tools, and every tool goes through the semantic
service. The model never sees the warehouse or writes SQL: it can only ask for
metrics the semantic layer defines, cut by dimensions those metrics support,
and it gets each metric's status and caveats with the numbers. That is the
pattern for embedding AI in an app without letting it invent a join.

Credentials come from the environment (ANTHROPIC_API_KEY, or an `ant auth
login` profile). Server-side refusal fallbacks are on: if the model declines
a request, the API re-runs it on a fallback model inside the same call.
"""
from __future__ import annotations

import json
import sys
from contextvars import ContextVar

import anthropic
from anthropic import beta_tool

from serving.semantic_service import MetricRequestError, SemanticService

MODEL = "claude-opus-5-5"
SYSTEM = """You answer business questions using governed metrics only.
Use list_metrics and describe_metric to find the right metric, valid_dimensions before
grouping, then query_metrics. Report each metric's status and caveats with its numbers,
say plainly when a metric is provisional, and never estimate a number the tools did not
return. If a metric cannot be cut the way the user asked, say why."""

svc = SemanticService()

#: Called with (tool, arguments, result) after every tool call - how a UI shows
#: what the model asked the semantic layer for.
on_tool: ContextVar = ContextVar("on_tool", default=None)


def _call(fn, *args, **kwargs) -> str:
    try:
        result = fn(*args, **kwargs)
        out = json.dumps(result, default=str)
    except MetricRequestError as exc:
        result = {"error": str(exc)}
        out = json.dumps(result)
    hook = on_tool.get()
    if hook:
        hook(getattr(fn, "__name__", "query_metrics"), {"args": args, **kwargs}, result)
    return out


@beta_tool
def list_metrics() -> str:
    """List every business metric with its name, label, status, owner and description."""
    return _call(svc.list_metrics)


@beta_tool
def describe_metric(name: str) -> str:
    """Get one metric's definition, status, caveats, valid dimensions and dashboards.

    Args:
        name: The metric's name, e.g. on_time_delivery_rate.
    """
    return _call(svc.describe_metric, name)


@beta_tool
def valid_dimensions(metrics: list[str]) -> str:
    """List the group-by names every one of these metrics supports together.

    Args:
        metrics: Metric names.
    """
    return _call(svc.valid_dimensions, metrics)


@beta_tool
def query_metrics(metrics: list[str], group_by: list[str] | None = None,
                  order_by: list[str] | None = None, limit: int = 100,
                  start: str | None = None, end: str | None = None) -> str:
    """Query metrics, optionally grouped, with status and caveats beside the numbers.

    Args:
        metrics: Metric names.
        group_by: Dimension names such as site__site_name or metric_time__quarter.
        order_by: Names to sort by; prefix '-' for descending, e.g. -metric_time__month.
        limit: Maximum rows to return.
        start: ISO date; earliest metric_time to include.
        end: ISO date; latest metric_time to include.
    """
    def query_metrics():
        result = svc.query(metrics, group_by=group_by, order_by=order_by,
                           limit=min(limit, 500), start=start, end=end)
        result.pop("sql", None)
        return result
    return _call(query_metrics, metrics=metrics, group_by=group_by, start=start, end=end)


def ask(question: str, history: list[dict] | None = None) -> str:
    """Answer a question; `history` holds earlier turns as {"role", "content"} text messages."""
    client = anthropic.Anthropic()
    runner = client.beta.messages.tool_runner(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM,
        output_config={"effort": "medium"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        tools=[list_metrics, describe_metric, valid_dimensions, query_metrics],
        messages=[*(history or []), {"role": "user", "content": question}],
    )
    final = None
    for message in runner:
        final = message
    if final is None:
        return ""
    if final.stop_reason == "refusal":
        return "The request was declined."
    return "".join(b.text for b in final.content if b.type == "text")


if __name__ == "__main__":
    question = " ".join(sys.argv[1:]) or "How is on-time delivery trending by site this year?"
    print(ask(question))
