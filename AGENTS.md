# Building an app on this platform

For coding agents (and people) building apps that use the platform's data.

## The rule

Get numbers from the semantic layer, never by writing SQL against the
warehouse. Every metric has one definition, a status, an owner and caveats;
show the status and caveats wherever you show the number. If the platform
refuses a request (a dimension a metric does not support, a metric with no
definition yet), show the reason - do not work around it.

## The API

Base URL: `http://localhost:8000` locally (`make serve`); in Azure, the data
service URL from the deployment, behind Entra ID. OpenAPI: `/openapi.json`,
interactive docs at `/docs`.

| Call | Returns |
|---|---|
| `GET /metrics` | KPIs: name, label, status, owner, description, format |
| `GET /metrics/{name}` | Definition, status, owner, caveats, `valid_dimensions`, `department_attributable`, the dashboards it is on |
| `POST /metrics/dimensions` `{"metrics": [...]}` | Group-by names valid for all of them together |
| `POST /query` `{"metrics", "group_by", "where", "order_by", "limit", "start", "end"}` | `columns`, `rows`, and `metrics` (status, caveats) beside them; HTTP 422 with a reason when refused |
| `GET /datasets`, `GET /datasets/{name}?limit=&offset=` | Pre-aggregated marts from the serving database, for fast app reads |

Group-by names: `site__site_name`, `customer__industry`,
`employee__department_name`, `metric_time__month` (grains: day, week, month,
quarter, year, fiscal_quarter, fiscal_year). Filters use MetricFlow syntax:
`{{ Dimension('site__site_name') }} = 'Reno NV Distribution Center'`.
Formats: `percent` is a 0-1 ratio, `currency_usd`, `days`, `count`.

## Embedding AI

Give the model the four tools in `apps/examples/ask_metrics/app.py` (or the MCP
server at `/mcp/`), never a SQL tool. The model can then only reach governed
metrics, and its answers carry their caveats.

## Python, in this repo

```python
from serving.semantic_service import SemanticService
svc = SemanticService()
svc.query(["on_time_delivery_rate"], group_by=["site__site_name", "metric_time__quarter"])
```
