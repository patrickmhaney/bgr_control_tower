"""Publish the warehouse file to raw storage, versioned, for read-only consumers.

    python -m serving.publish     # <bronze_root>/../warehouse/<env>/warehouse.duckdb

Dagster is the only writer of the DuckDB file. The data service and anything
else that reads it downloads the latest published copy and opens it
read-only, so readers never contend with the build. Locally this is a copy
under .data/published/.
"""
from __future__ import annotations

import datetime as dt
import os
import shutil

from core.settings import settings


def publish_warehouse() -> str:
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    src = settings.warehouse_path
    account = settings.get("storage_account")
    if account:
        import fsspec

        fs = fsspec.filesystem("az", account_name=account)
        for name in (f"warehouse/{settings.env}/warehouse.duckdb",
                     f"warehouse/{settings.env}/versions/{stamp}/warehouse.duckdb"):
            fs.put(src, name)
        return f"az://warehouse/{settings.env}/warehouse.duckdb"
    out = os.path.join(settings.data_dir, "published")
    os.makedirs(os.path.join(out, "versions", stamp), exist_ok=True)
    shutil.copy2(src, os.path.join(out, "warehouse.duckdb"))
    shutil.copy2(src, os.path.join(out, "versions", stamp, "warehouse.duckdb"))
    return os.path.join(out, "warehouse.duckdb")


if __name__ == "__main__":
    print(publish_warehouse())
