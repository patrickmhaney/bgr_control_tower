"""One writer at a time: a lock file the pipeline's step commands take while they run.

The warehouse is a single DuckDB file and dbt shares one target folder, so two
runs at once (a terminal, the Studio, `make run` in another window) collide
halfway. Every step command that writes holds `<data_dir>/pipeline.lock` for
its duration; a second one stops at once with the holder's name, and readers
such as the Studio check it before opening the warehouse. A lock left by a
process that no longer exists is taken over.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from contextlib import contextmanager

from core.settings import settings


class PipelineBusy(RuntimeError):
    pass


def _path() -> str:
    return os.path.join(settings.data_dir, "pipeline.lock")


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def holder() -> dict | None:
    """Who holds the lock, or None. A lock left by a dead process does not count."""
    try:
        with open(_path()) as fh:
            info = json.load(fh)
    except (OSError, ValueError):
        return None
    return info if _alive(info.get("pid", -1)) else None


@contextmanager
def held(command: str):
    os.makedirs(settings.data_dir, exist_ok=True)
    info = {"pid": os.getpid(), "command": command,
            "started": dt.datetime.now().isoformat(timespec="seconds")}
    for _ in range(2):
        try:
            fd = os.open(_path(), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            current = holder()
            if current:
                raise PipelineBusy(f"The pipeline is busy: {current['command']} "
                                   f"(pid {current['pid']}, since {current['started']}).") from None
            os.remove(_path())  # stale: its process is gone
    else:
        raise PipelineBusy("Could not take the pipeline lock.")
    with os.fdopen(fd, "w") as fh:
        json.dump(info, fh)
    try:
        yield
    finally:
        try:
            with open(_path()) as fh:
                mine = json.load(fh).get("pid") == info["pid"]
            if mine:
                os.remove(_path())
        except (OSError, ValueError):
            pass  # `ctl reset` deletes the data directory, lock included
