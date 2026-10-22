"""Control Tower Studio: the architecture, and the pipeline run live, for people who don't read code.

    python -m apps.studio            # http://localhost:8800

Two screens. The map draws the components, the contracts between them, and
what each stack option would put in each box (apps/studio/content.yml and
evaluation/components.yml). Run steps through the pipeline: every button runs
the platform's own step commands in a subprocess and streams their progress,
then apps/studio/probe.py reads what happened and runs the boundary checks.

It runs commands on this machine, so it listens on localhost only. On a VM it
belongs behind Entra ID sign-in, like the data service.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import sys
import time
import uuid

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.settings import ROOT, settings

from . import contracts, pipeline

HERE = os.path.dirname(os.path.abspath(__file__))
COMPONENTS = os.path.join(ROOT, "evaluation", "components.yml")
TARGET = os.path.join(ROOT, "transform", "target")

app = FastAPI(title="Control Tower Studio", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")


# ------------------------------------------------------------------ state --
def _state_path() -> str:
    return os.path.join(settings.data_dir, "studio.json")


def _load_state() -> dict:
    try:
        with open(_state_path()) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


STATE = {"provider": settings.mdm_provider, "results": {}, **_load_state()}


def _save_state() -> None:
    os.makedirs(settings.data_dir, exist_ok=True)
    with open(_state_path(), "w") as fh:
        json.dump(STATE, fh, indent=2, default=str)


# ------------------------------------------------------------------- jobs --
class Job:
    def __init__(self, steps: list[dict]):
        self.id = uuid.uuid4().hex[:12]
        self.steps = steps
        self.events: list[dict] = []
        self.done = False
        self.ok = True

    def emit(self, **event) -> None:
        self.events.append(event)


JOBS: dict[str, Job] = {}
CURRENT: Job | None = None


def _env() -> dict:
    return {**os.environ, "CT_MDM_PROVIDER": STATE["provider"], "DBT_USE_COLORS": "false",
            "PYTHONUNBUFFERED": "1"}


async def _stream(job: Job, step: str, args: list[str], on_line=None) -> tuple[int, list[str]]:
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", *args, cwd=ROOT, env=_env(),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    lines = []
    assert proc.stdout
    async for raw in proc.stdout:
        line = pipeline.clean_line(raw.decode(errors="replace"))
        if not line:
            continue
        lines.append(line)
        done = pipeline.progress(line)
        job.emit(type="log", step=step, line=line, progress=done)
        if on_line:
            on_line(line)
    return await proc.wait(), lines


async def _probe(step: str, since: float) -> dict:
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "apps.studio.probe", step, cwd=ROOT, env={**_env(), "STUDIO_SINCE": str(since)},
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = await proc.communicate()
    if proc.returncode:
        tail = err.decode(errors="replace").strip().splitlines()[-1:] or ["no output"]
        return {"facts": [], "checks": [], "error": tail[0]}
    return json.loads(out.decode().strip().splitlines()[-1])


def _with_previous(step: str, facts: list[dict]) -> list[dict]:
    """Attach the value each fact had after the previous run of this step."""
    before = {f["label"]: f.get("raw") for f in STATE["results"].get(step, {}).get("facts", [])}
    return [{**f, "prev": before.get(f["label"])} for f in facts]


async def _run(job: Job) -> None:
    global CURRENT
    try:
        for i, step in enumerate(job.steps):
            sid = step["id"]
            if i:
                await asyncio.sleep(0.6)  # a beat between steps, so a room can follow along
            job.emit(type="step", step=sid, status="running")
            started = time.time()
            lines: list[str] = []
            for cmd in step["commands"]:
                args = [a.replace("{provider}", STATE["provider"]) for a in cmd]
                job.emit(type="log", step=sid, line="$ python -m " + " ".join(args), progress=None)
                code, out = await _stream(job, sid, args)
                lines += out
                if code:
                    job.emit(type="step", step=sid, status="failed",
                             reason=f"The step stopped with an error (exit code {code}).")
                    job.ok = False
                    return
            if sid == "reset":
                STATE["results"] = {}
                _save_state()
                job.emit(type="step", step=sid, status="ok")
                continue
            job.emit(type="step", step=sid, status="checking")
            result = await _probe(sid, started)
            facts = _with_previous(sid, pipeline.facts_from_log(sid, lines) + result["facts"])
            result = {**result, "facts": facts, "finished_at": dt.datetime.now().isoformat(timespec="seconds")}
            held = all(c["passed"] for c in result["checks"]) and "error" not in result
            STATE["results"][sid] = {**result, "status": "ok" if held else "failed"}
            _save_state()
            job.emit(type="result", step=sid, result=result)
            if not held:
                job.emit(type="step", step=sid, status="failed",
                         reason=result.get("error") or "A boundary check failed, so the pipeline stops here.")
                job.ok = False
                return
            job.emit(type="step", step=sid, status="ok")
    except Exception as exc:  # noqa: BLE001 - surface anything to the screen rather than hang
        job.ok = False
        job.emit(type="step", step=job.steps[0]["id"], status="failed", reason=str(exc))
    finally:
        job.done = True
        job.emit(type="done", ok=job.ok)
        CURRENT = None


def _content() -> dict:
    with open(os.path.join(HERE, "content.yml")) as fh:
        return yaml.safe_load(fh)


def _live() -> bool:
    """After day 0 the frozen golden answers no longer apply; compare live instead."""
    # Don't open the source database while a job may be writing it.
    clock = STATE.get("clock") if CURRENT and STATE.get("clock") else _clock()
    return clock.get("today") != _counts()["as_of"]


async def _run_tests(job: Job, cid: str, suites: list[tuple[int, dict]]) -> None:
    global CURRENT
    step = f"test:{cid}"
    try:
        live = _live()
        for i, suite in suites:
            job.emit(type="suite", index=i, status="running")
            seen = {"pass": 0, "fail": 0, "skip": 0, "warn": 0}

            def on_line(line, i=i, suite=suite, seen=seen):
                case = contracts.parse(suite["kind"], line)
                if case:
                    seen[case["status"]] += 1
                    job.emit(type="case", index=i, case=case)

            args = contracts.command(suite, live)
            job.emit(type="log", step=step, line="$ python -m " + " ".join(args), progress=None)
            code, _ = await _stream(job, step, args, on_line)
            ok = code == 0 and not seen["fail"]
            job.ok &= ok
            job.emit(type="suite", index=i, status="pass" if ok else "fail", counts=seen, code=code)
    except Exception as exc:  # noqa: BLE001
        job.ok = False
        job.emit(type="log", step=step, line=f"error: {exc}", progress=None)
    finally:
        job.done = True
        job.emit(type="done", ok=job.ok)
        CURRENT = None


# -------------------------------------------------------------------- api --
@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "static", "index.html"))


def _counts() -> dict:
    from evaluation.golden import GOLDEN

    out = {}
    with open(GOLDEN) as fh:
        golden = yaml.safe_load(fh)
    out["golden"] = len(golden["queries"])
    out["as_of"] = str(golden["as_of"])
    try:
        with open(os.path.join(TARGET, "semantic_manifest.json")) as fh:
            metrics = json.load(fh)["metrics"]
        out["metrics"] = sum(1 for m in metrics if ((m.get("config") or {}).get("meta") or {}).get("role") == "kpi")
        with open(os.path.join(TARGET, "manifest.json")) as fh:
            nodes = json.load(fh)["nodes"].values()
        out["star"] = sum(1 for n in nodes if n["resource_type"] == "model" and n["schema"].endswith("gold"))
    except OSError:
        pass
    return out


@app.get("/api/map")
def architecture():
    content = _content()
    with open(COMPONENTS) as fh:
        components = yaml.safe_load(fh)["components"]
    stacks = [s["id"] for s in content["stacks"]]

    def tools(node: dict) -> dict:
        comp = components.get(node.get("component") or "")
        out = {}
        for stack in stacks:
            if node.get("kind") == "source":
                out[stack] = {"tool": node["tool"], "swap": "source"}
            elif node.get("fixed") or not comp:
                out[stack] = {"tool": node["tool"], "swap": "stays"}
            elif stack == "baseline":
                out[stack] = {"tool": node["tool"], "swap": "baseline"}
            else:
                tool = comp["candidates"].get(stack) or "none"
                if tool == "none":
                    swap = "none"
                elif tool.lower().startswith(node["tool"].lower()):
                    swap = "same"
                else:
                    swap = (node.get("swap") or {}).get(stack) or str(comp.get("swap_cost", "")).split()[0]
                out[stack] = {"tool": "Not covered" if tool == "none" else tool, "swap": swap}
        return out

    def detail(node: dict) -> dict:
        comp = components.get(node.get("component") or "") or {}
        return {"contract": comp.get("contract"), "test": comp.get("test"), "note": comp.get("note"),
                "swap_cost": comp.get("swap_cost"), "other": (comp.get("candidates") or {}).get("other") or [],
                "requirements": comp.get("requirements") or []}

    for group in ("nodes", "foundation"):
        for node in content[group]:
            node["stacks"] = tools(node)
            node["detail"] = detail(node)
    content["counts"] = {**_counts(), "contracts": len(content["contracts"])}
    return content


def _clock() -> dict:
    from sources import clock
    from sources import generate as g

    if not os.path.exists(settings.mock_db):
        return {"initialised": False, "start": g.INITIAL_DATE.isoformat(), "end": g.TIMELINE_END.isoformat()}
    today = clock.status()["today"]
    return {"initialised": True, "today": today.isoformat(), "start": g.INITIAL_DATE.isoformat(),
            "end": g.TIMELINE_END.isoformat(), "day": (today - g.INITIAL_DATE).days,
            "days": (g.TIMELINE_END - g.INITIAL_DATE).days}


@app.get("/api/state")
def state():
    # Only read the source database between jobs: the pipeline may be writing it.
    clock = STATE.get("clock") if CURRENT else None
    if clock is None:
        clock = _clock()
        STATE["clock"] = clock
    return {"clock": clock, "built": os.path.exists(settings.warehouse_path), "provider": STATE["provider"],
            "results": STATE["results"], "steps": [{k: s[k] for k in ("id", "title", "lead", "node")}
                                                  | {"checks": s.get("checks", [])} for s in pipeline.STEPS],
            "job": {"id": CURRENT.id, "steps": [s["id"] for s in CURRENT.steps]} if CURRENT else None,
            "counts": _counts()}


class RunRequest(BaseModel):
    steps: list[str] = []
    reset: bool = False


@app.post("/api/run")
async def run(req: RunRequest):
    global CURRENT
    if CURRENT:
        raise HTTPException(409, "A run is already in progress.")
    unknown = [s for s in req.steps if s not in pipeline.BY_ID]
    if unknown or not (req.steps or req.reset):
        raise HTTPException(400, f"Unknown steps: {unknown}" if unknown else "Nothing to run.")
    steps = ([pipeline.RESET] if req.reset else []) + [pipeline.BY_ID[s] for s in req.steps]
    job = Job(steps)
    JOBS[job.id] = job
    CURRENT = job
    asyncio.get_running_loop().create_task(_run(job))
    return {"id": job.id, "steps": [s["id"] for s in steps]}


@app.get("/api/jobs/{job_id}/events")
async def events(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "No such run.")

    async def stream():
        sent = 0
        while True:
            while sent < len(job.events):
                yield f"data: {json.dumps(job.events[sent], default=str)}\n\n"
                sent += 1
            if job.done and sent >= len(job.events):
                return
            await asyncio.sleep(0.1)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})


class ProviderRequest(BaseModel):
    provider: str


@app.post("/api/provider")
def provider(req: ProviderRequest):
    if req.provider not in ("splink", "rules"):
        raise HTTPException(400, "The matcher is splink or rules.")
    if CURRENT:
        raise HTTPException(409, "Wait for the run to finish.")
    STATE["provider"] = req.provider
    _save_state()
    return {"provider": req.provider}


@app.get("/api/contracts/{cid}")
def contract(cid: str):
    c = _content()["contracts"].get(cid)
    if not c:
        raise HTTPException(404, "No such contract.")
    last = None
    for step, r in STATE["results"].items():
        for check in r.get("checks", []):
            if check["id"] == cid:
                last = {"step": step, "passed": check["passed"], "at": r.get("finished_at")}
    return {"id": cid, "name": c["name"], "promise": c["promise"], "proof": c["proof"],
            "enforced": c.get("enforced"), "last": last, "live": _live(),
            "files": [contracts.excerpt(f) for f in c.get("files", [])],
            "suites": [{"title": su["title"], "kind": su["kind"], "note": su.get("note"),
                        "optional": bool(su.get("optional")), "cases": contracts.cases(su)}
                       for su in c.get("suites", [])]}


class TestRequest(BaseModel):
    suites: list[int] | None = None


@app.post("/api/contracts/{cid}/run")
async def run_contract(cid: str, req: TestRequest):
    global CURRENT
    if CURRENT:
        raise HTTPException(409, "Something is already running.")
    c = _content()["contracts"].get(cid)
    if not c or not c.get("suites"):
        raise HTTPException(404, "This contract has no tests to run.")
    all_suites = list(enumerate(c["suites"]))
    chosen = [(i, su) for i, su in all_suites
              if (req.suites is None and not su.get("optional")) or (req.suites and i in req.suites)]
    job = Job([{"id": f"test:{cid}", "commands": []}])
    JOBS[job.id] = job
    CURRENT = job
    asyncio.get_running_loop().create_task(_run_tests(job, cid, chosen))
    return {"id": job.id, "suites": [i for i, _ in chosen]}
