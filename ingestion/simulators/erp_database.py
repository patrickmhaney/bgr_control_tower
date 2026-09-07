"""Sage X3, read as a database.

PRODUCTION SWAP
---------------
Replace `connect()` with a SQL Server or Oracle connection - pyodbc, pymssql or
oracledb - pointed at a read replica of the production folder, and change the
identifier quoting in `_quote` if the target needs it. Nothing else moves: the
extraction is already expressed as parameterised SQL over an explicit column
list, which is what you want against a real ERP anyway.

WHY IT LOOKS LIKE THIS
----------------------
Two properties of a real ERP read are reproduced deliberately:

1. Columns are enumerated, never `SELECT *`. A `SELECT *` against X3 pulls
   hundreds of columns you do not need, and it breaks silently when Sage adds
   one in an upgrade. The column list also documents what the warehouse
   actually depends on, which is what makes an upgrade impact assessment
   possible.
2. Predicates are pushed to the source. The window is computed here and sent as
   SQL, so the database does the filtering. Pulling everything and filtering in
   Python is the classic way to make a nightly job take four hours.
"""
from __future__ import annotations

import datetime as dt

from . import _mock_db

SCHEMA = "sage_x3"


def _quote(identifier: str) -> str:
    """X3 column names are case-sensitive and contain no exotic characters.

    SQL Server would use [brackets]; Oracle and DuckDB use "double quotes".
    """
    return '"' + identifier.replace('"', '""') + '"'


def columns_of(table: str) -> list[str]:
    """The column list is discovered once and then pinned in production.

    Here it is read from the catalogue so the POC stays in step with the mock.
    Against a real folder you would freeze this list and alert when the source
    gains or loses a column, because a silently added column is how a schema
    drift becomes a wrong number three months later.
    """
    return [
        r["column_name"]
        for r in _mock_db.rows(
            "select column_name from duckdb_columns() "
            "where schema_name = ? and table_name = ? order by column_index",
            [SCHEMA, table],
        )
    ]


def read_full(table: str) -> list[dict]:
    cols = ", ".join(_quote(c) for c in columns_of(table))
    return _mock_db.rows(f'select {cols} from {SCHEMA}."{table}"')


def read_modified_since(table: str, cursor_column: str, since: dt.date | None) -> list[dict]:
    """Window on the table's own modification date.

    Note the date semantics: X3's UPDDAT_0 is a DATE, not a timestamp, so `>=`
    is correct and `>` would drop rows modified later on the boundary day.
    """
    cols = ", ".join(_quote(c) for c in columns_of(table))
    if since is None:
        return _mock_db.rows(f'select {cols} from {SCHEMA}."{table}"')
    return _mock_db.rows(
        f'select {cols} from {SCHEMA}."{table}" where {_quote(cursor_column)} >= ?',
        [since],
    )


def read_header_window(
    table: str,
    parent_table: str,
    join_column: str,
    parent_date_column: str,
    since: dt.date | None,
) -> list[dict]:
    """Window a table through its parent's business date.

    The join is a semi-join rather than an inner join so the child's row count
    cannot be inflated by a parent with duplicates - a real risk on X3 tables
    where the "primary key" is a convention rather than a constraint.
    """
    cols = ", ".join(f'child.{_quote(c)}' for c in columns_of(table))
    if since is None:
        return _mock_db.rows(f'select {cols} from {SCHEMA}."{table}" as child')

    if parent_table == table:
        return _mock_db.rows(
            f'select {cols} from {SCHEMA}."{table}" as child '
            f'where child.{_quote(parent_date_column)} >= ?',
            [since],
        )

    return _mock_db.rows(
        f'select {cols} from {SCHEMA}."{table}" as child '
        f"where exists ("
        f'  select 1 from {SCHEMA}."{parent_table}" as parent '
        f"  where trim(parent.{_quote(join_column)}) = trim(child.{_quote(join_column)}) "
        f"    and parent.{_quote(parent_date_column)} >= ?"
        f")",
        [since],
    )
