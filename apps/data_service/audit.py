"""Audit log: who asked for what, through which route.

One JSON line per request on stdout, which Container Apps ships to Log
Analytics; locally it is also appended to <data_dir>/audit/queries.jsonl.
In Azure the caller's identity comes from Container Apps authentication
(Entra ID) through the X-MS-CLIENT-PRINCIPAL-NAME header.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from contextvars import ContextVar

from core.settings import settings

caller: ContextVar[str] = ContextVar("caller", default="local")


def record(route: str, action: str, **details) -> None:
    entry = {"at": dt.datetime.now(dt.UTC).isoformat(), "route": route,
             "action": action, "caller": caller.get(), **details}
    line = json.dumps(entry, default=str)
    print(line, flush=True)
    if settings.env == "local":
        path = os.path.join(settings.data_dir, "audit", "queries.jsonl")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a") as fh:
            fh.write(line + "\n")
