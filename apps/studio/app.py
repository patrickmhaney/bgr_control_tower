"""Control Tower Studio: the architecture, the pipeline run live, and preview consumers of its data.

    python -m apps.studio            # http://localhost:8800

The map draws the components, the contracts between them, and what each stack
option would put in each box (apps/studio/content.yml and
evaluation/components.yml). Run steps through the pipeline: every button runs
the platform's own step commands in a subprocess and streams their progress,
then apps/studio/probe.py reads what happened and runs the boundary checks.

Three preview screens read what the pipeline produced, each through an
existing route: dashboards over the Power BI cube (contract C7), SQL over gold
and the marts plus metric queries through the semantic layer (C5, C6), and a
chat that can only call the governed metric tools (the MCP tools, C6).

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

from core import lock
from core.settings import ROOT, settings

from . import contracts, data, pipeline

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
    clock = STATE.get("clock") if (CURRENT or lock.holder()) and STATE.get("clock") else _clock()
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
    clock = STATE.get("clock") if CURRENT or lock.holder() else None
    if clock is None:
        clock = _clock()
        STATE["clock"] = clock
    return {"clock": clock, "built": os.path.exists(settings.warehouse_path), "provider": STATE["provider"],
            "results": STATE["results"], "steps": [{k: s[k] for k in ("id", "title", "lead", "node")}
                                                  | {"checks": s.get("checks", [])} for s in pipeline.STEPS],
            "job": {"id": CURRENT.id, "steps": [s["id"] for s in CURRENT.steps]} if CURRENT else None,
            "busy": data.busy_reason(bool(CURRENT)),
            "counts": _counts()}


class RunRequest(BaseModel):
    steps: list[str] = []
    reset: bool = False


@app.post("/api/run")
async def run(req: RunRequest):
    global CURRENT
    if CURRENT:
        raise HTTPException(409, "A run is already in progress.")
    if lock.holder():
        raise HTTPException(409, data.busy_reason(False))
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
    if CURRENT or lock.holder():
        raise HTTPException(409, data.busy_reason(bool(CURRENT)) or "Something is already running.")
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


# ------------------------------------------------------- preview screens --
def _readable() -> None:
    reason = data.busy_reason(bool(CURRENT))
    if reason:
        raise HTTPException(409, reason)
    if not os.path.exists(settings.warehouse_path):
        raise HTTPException(409, "There is no data yet. Initialize on the Run the pipeline screen.")


def _today() -> dt.date:
    clock = STATE.get("clock") or _clock()
    return dt.date.fromisoformat(clock["today"]) if clock.get("today") else dt.date.today()


@app.get("/api/dashboards")
def dashboards():
    return {"pages": data.pages()}


@app.get("/api/dashboards/{name}")
def dashboard(name: str, metric: str | None = None, period: str = "ytd", dim: str | None = None):
    if name not in {p["id"] for p in data.pages()} or period not in ("month", "ytd", "12m"):
        raise HTTPException(404, "No such page.")
    _readable()
    return data.page(name, metric, period, _today(), dim)


@app.get("/api/query/schema")
def query_schema():
    _readable()
    return {"tables": data.schema(), "examples": data.examples(), "limit": data.ROW_LIMIT}


class SqlRequest(BaseModel):
    sql: str


@app.post("/api/query/sql")
def query_sql(req: SqlRequest):
    _readable()
    try:
        return data.run_sql(req.sql)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


_SVC = None


def _svc():
    """One semantic service for the Studio, its warehouse reads taken one at a time."""
    global _SVC
    if _SVC is None:
        from serving.semantic_service import SemanticService

        svc = SemanticService()

        def locked(fn):
            def wrapper(*args, **kwargs):
                with data.WAREHOUSE:
                    return fn(*args, **kwargs)
            return wrapper

        svc.client.query = locked(svc.client.query)
        svc.as_of_date = locked(svc.as_of_date)
        _SVC = svc
    return _SVC


@app.get("/api/metrics")
def metrics():
    return {"metrics": _svc().list_metrics()}


class DimensionsRequest(BaseModel):
    metrics: list[str]


@app.post("/api/metrics/dimensions")
def metric_dimensions(req: DimensionsRequest):
    from serving.semantic_service import MetricRequestError

    try:
        return {"dimensions": _svc().valid_dimensions(req.metrics) if req.metrics else []}
    except MetricRequestError as exc:
        raise HTTPException(400, str(exc)) from None


class MetricQueryRequest(BaseModel):
    metrics: list[str]
    group_by: list[str] = []
    start: str | None = None


@app.post("/api/metrics/query")
def metric_query(req: MetricQueryRequest):
    from serving.semantic_service import MetricRequestError

    _readable()
    order = [g for g in req.group_by if g.startswith("metric_time")]
    try:
        return _svc().query(req.metrics, group_by=req.group_by, order_by=order or None,
                            limit=500, start=req.start)
    except MetricRequestError as exc:
        raise HTTPException(400, str(exc)) from None


@app.get("/api/ask/status")
def ask_status():
    try:
        import anthropic  # noqa: F401

        from apps.examples.ask_metrics.app import MODEL
    except ImportError:
        return {"available": False, "reason": "The anthropic package is not installed (uv sync --extra examples)."}
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return {"available": False, "model": MODEL,
                "reason": "Set ANTHROPIC_API_KEY in the environment and restart the Studio."}
    return {"available": True, "model": MODEL}


class AskRequest(BaseModel):
    question: str
    history: list[dict] = []


def _summarize(tool: str, result) -> str:
    if isinstance(result, dict) and "error" in result:
        return "Refused: " + str(result["error"])
    if tool == "list_metrics":
        return f"{len(result)} metrics"
    if tool == "describe_metric":
        return f"{result.get('label')} ({result.get('status')})"
    if tool == "valid_dimensions":
        return f"{len(result)} valid dimensions"
    if tool == "query_metrics":
        return f"{len(result.get('rows', []))} rows"
    return ""


@app.post("/api/ask")
async def ask(req: AskRequest):
    if not ask_status()["available"]:
        raise HTTPException(409, ask_status()["reason"])
    _readable()
    from apps.examples.ask_metrics import app as ask_app

    ask_app.svc = _svc()
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def hook(tool, arguments, result):
        args = {k: v for k, v in arguments.items() if k != "args" and v}
        if arguments.get("args"):
            args["metrics" if tool == "valid_dimensions" else "name"] = arguments["args"][0]
        event = {"type": "tool", "tool": tool, "input": args, "summary": _summarize(tool, result)}
        loop.call_soon_threadsafe(queue.put_nowait, event)

    def work():
        ask_app.on_tool.set(hook)
        try:
            history = [{"role": m["role"], "content": m["content"]} for m in req.history
                       if m.get("role") in ("user", "assistant") and m.get("content")]
            text = ask_app.ask(req.question, history)
            event = {"type": "answer", "text": text}
        except Exception as exc:  # noqa: BLE001 - show the API's message in the chat
            event = {"type": "error", "message": str(exc).splitlines()[0]}
        loop.call_soon_threadsafe(queue.put_nowait, event)
        loop.call_soon_threadsafe(queue.put_nowait, None)

    loop.run_in_executor(None, work)

    async def stream():
        while (event := await queue.get()) is not None:
            yield json.dumps(event, default=str) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson")
