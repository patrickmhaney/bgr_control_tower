"""The golden answers: the semantic layer must reproduce the frozen numbers."""
import pytest

from evaluation.golden import run

pytestmark = pytest.mark.pipeline


def test_golden_answers_pass_on_duckdb():
    assert run("check", backend="duckdb") == 0


@pytest.mark.tsql
def test_golden_answers_pass_through_the_tsql_path():
    assert run("check", backend="tsql") == 0
