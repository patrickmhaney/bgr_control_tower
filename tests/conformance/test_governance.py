"""Governance and portability gates (rule 3, C4, C5)."""
import pytest

pytestmark = pytest.mark.pipeline


def test_governance_lint_is_clean():
    from semantic.lint import lint

    assert lint() == []


def test_silver_and_gold_port_to_tsql_and_snowflake():
    from checks.portability import check

    assert check() == []
