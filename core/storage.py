"""Read and write files in raw storage, locally or in ADLS, with one code path."""
from __future__ import annotations

import os

import pyarrow as pa

from core.settings import settings


def storage_options() -> dict[str, str] | None:
    """Credentials for az:// paths. No key: the managed identity is used."""
    account = settings.get("storage_account")
    return {"azure_storage_account_name": account} if account else None


def join(*parts: str) -> str:
    return "/".join(p.rstrip("/") for p in parts)


def write_delta(path: str, table: pa.Table, mode: str = "overwrite") -> None:
    from deltalake import write_deltalake

    if "://" not in path:
        os.makedirs(path, exist_ok=True)
    write_deltalake(path, table, mode=mode, schema_mode="overwrite",
                    storage_options=storage_options())


def write_parquet(path: str, table: pa.Table) -> None:
    import pyarrow.parquet as pq

    if "://" in path:
        import fsspec

        fs, inner = fsspec.core.url_to_fs(path, **(storage_options() or {}))
        with fs.open(inner, "wb") as fh:
            pq.write_table(table, fh)
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    pq.write_table(table, path)
