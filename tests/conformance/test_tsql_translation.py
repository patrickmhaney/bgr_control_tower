"""The T-SQL path (decision D10): MetricFlow's Postgres-style SQL must translate.

Compiling needs no SQL Server: MetricFlow renders each golden query as
Postgres-style SQL and sqlglot must translate it to T-SQL without reporting
anything unsupported. Running the result needs TSQL_URL - see
test_golden_answers.py and the CI workflow, which starts a SQL Server
container and loads gold into it.
"""
import pytest
import yaml

from core import project
from serving.semantic_service import SemanticService

pytestmark = pytest.mark.pipeline


def test_every_golden_query_compiles_to_tsql():
    svc = SemanticService(backend="tsql", tsql_url="mssql://reader:unused@localhost:1433/warehouse")
    with open(project.current().golden) as fh:
        queries = [q for q in yaml.safe_load(fh)["queries"] if "expect_refusal" not in q]
    failures = []
    for q in queries:
        try:
            sql = svc.compile(q["metrics"], group_by=q.get("group_by"), where=q.get("where"))
            assert "date_trunc" not in sql.lower()          # a T-SQL engine has no DATE_TRUNC
        except Exception as exc:  # noqa: BLE001 - report every query, not just the first
            failures.append(f"{q['id']}: {str(exc).splitlines()[0]}")
    assert failures == [], failures
