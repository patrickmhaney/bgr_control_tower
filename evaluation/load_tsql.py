"""Copy gold into a SQL Server database, for the T-SQL path test (decision D10).

    TSQL_URL=mssql://sa:Passw0rd!@localhost:1433/warehouse python -m evaluation.load_tsql

Creates the database if needed, then each gold table in schema `gold` with
T-SQL types, and bulk-inserts the rows. CI runs this against a SQL Server
2022 container, then runs the golden answers through the T-SQL backend. It is
a compatibility test, not a second stack: nothing else in the platform
touches SQL Server.
"""
from __future__ import annotations

import os
import re
import sys
from urllib.parse import urlparse

import duckdb

from core.settings import settings

TYPES = {"varchar": "nvarchar(400)", "integer": "int", "bigint": "bigint", "double": "float",
         "date": "date", "boolean": "bit"}
BATCH = 1000


def _tsql_type(duck: str) -> str:
    duck = duck.lower()
    m = re.match(r"decimal\((\d+),\s*(\d+)\)", duck)
    if m:
        return f"decimal({m.group(1)},{m.group(2)})"
    return TYPES.get(duck, "nvarchar(400)")


def load(url: str) -> None:
    import pymssql

    u = urlparse(url)
    database = u.path.lstrip("/") or "warehouse"
    admin = pymssql.connect(server=u.hostname, port=u.port or 1433, user=u.username,
                            password=u.password, autocommit=True)
    admin.cursor().execute(f"if db_id('{database}') is null create database [{database}]")
    admin.close()
    con = pymssql.connect(server=u.hostname, port=u.port or 1433, user=u.username,
                          password=u.password, database=database)
    cur = con.cursor()
    cur.execute("if schema_id('gold') is null exec('create schema gold')")
    duck = duckdb.connect(settings.warehouse_path, read_only=True)
    tables = [r[0] for r in duck.execute(
        "select table_name from duckdb_tables() where schema_name = 'gold' order by 1").fetchall()]
    for t in tables:
        cols = duck.execute("select column_name, data_type from duckdb_columns() "
                            "where schema_name = 'gold' and table_name = ? order by column_index",
                            [t]).fetchall()
        cur.execute(f"if object_id('gold.{t}') is not null drop table gold.[{t}]")
        cur.execute(f"create table gold.[{t}] ("
                    + ", ".join(f"[{c}] {_tsql_type(d)}" for c, d in cols) + ")")
        rows = duck.execute(f'select * from gold."{t}"').fetchall()
        sql = f"insert into gold.[{t}] values ({', '.join(['%s'] * len(cols))})"
        for i in range(0, len(rows), BATCH):
            cur.executemany(sql, rows[i:i + BATCH])
        con.commit()
        print(f"tsql: gold.{t} {len(rows):,} rows")
    con.close()


if __name__ == "__main__":
    target = os.environ.get("TSQL_URL")
    if not target:
        sys.exit("Set TSQL_URL=mssql://user:password@host:port/database")
    load(target)
