"""FastAPI backend: start projects, stream the live feed, and resolve human gates.

Single demo user, no auth (CLAUDE.md non-goals). Endpoints are all `async def` so they share the
event loop with the pipeline tasks and the SQLite connection stays single-threaded.
"""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .config import load_settings
from .db import Store
from .gates import ApiGate, Decision
from .pipeline import LESSONS_KEY, Pipeline
from .provenance import ProvenanceLog

# (project_id, store, gate, log, executor_kind) -> Pipeline
PipelineFactory = Callable[[str, Store, ApiGate, ProvenanceLog, str], Pipeline]


class NewProject(BaseModel):
    question: str = Field(min_length=8, max_length=500)
    executor: Literal["contree", "local"] | None = None


class GateDecision(BaseModel):
    action: Literal["approve", "reject", "modify", "inject"]
    payload: str | None = Field(default=None, max_length=8000)


def default_pipeline_factory() -> PipelineFactory:
    from .literature import Literature
    from .models import ModelRouter
    from .sandbox import ContreeExecutor, LocalExecutor
    from .sandbox.resilient import ResilientExecutor

    settings = load_settings(need_tavily=True)
    allow_local = os.environ.get("PALISSY_ALLOW_LOCAL_FALLBACK") == "1"

    def factory(pid, store, gate, log, executor_kind):
        if executor_kind == "local":
            executor = LocalExecutor()
        else:
            executor = ContreeExecutor(session_key=f"palissy_{pid}")
            if allow_local:
                executor = ResilientExecutor(executor, LocalExecutor())
        return Pipeline(router=ModelRouter(settings, log),
                        literature=Literature(settings.tavily_api_key, log),
                        executor=executor, gate=gate, store=store, log=log)
    return factory


def create_app(store: Store | None = None, factory: PipelineFactory | None = None,
               default_executor: str | None = None) -> FastAPI:
    store = store or Store(load_settings().db_path)
    tasks: dict[str, asyncio.Task] = {}
    gates: dict[str, asyncio.Future] = {}
    state = {"factory": factory}
    executor_default = default_executor or os.environ.get("PALISSY_EXECUTOR", "contree")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store.interrupt_running()
        yield
        for t in tasks.values():
            t.cancel()

    app = FastAPI(title="Palissy", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.environ.get("PALISSY_CORS", "http://localhost:3000").split(","),
        allow_methods=["*"], allow_headers=["*"])

    def get_factory() -> PipelineFactory:
        if state["factory"] is None:
            state["factory"] = default_pipeline_factory()
        return state["factory"]

    def project_or_404(pid: str) -> dict:
        row = store.get_project(pid)
        if not row:
            raise HTTPException(404, "project not found")
        return dict(row)

    def summary(row: dict) -> dict:
        return {**row, "cost_usd": store.project_cost(row["id"]),
                "pending_gate": store.pending_gate(row["id"])}

    async def run_project(pid: str, question: str, executor_kind: str) -> None:
        log = ProvenanceLog(f"data/provenance_{pid}.jsonl", store=store, project_id=pid)
        gate = ApiGate(store, pid, gates, get_cycle=lambda: log.cycle)
        try:
            pipeline = get_factory()(pid, store, gate, log, executor_kind)
            await pipeline.run(question)
        except asyncio.CancelledError:
            store.update_project(pid, status="interrupted", error="cancelled")
            raise
        except Exception as exc:  # pipeline already marks failed; record why
            store.update_project(pid, status="failed", error=f"{type(exc).__name__}: {exc}"[:500])
        finally:
            tasks.pop(pid, None)

    @app.post("/projects", status_code=201)
    async def create_project(body: NewProject) -> dict:
        pid = store.create_project(body.question.strip())
        tasks[pid] = asyncio.create_task(
            run_project(pid, body.question.strip(), body.executor or executor_default))
        return summary(project_or_404(pid))

    @app.get("/projects")
    async def list_projects() -> list[dict]:
        return [summary(dict(r)) for r in store.list_projects()]

    @app.get("/projects/{pid}")
    async def get_project(pid: str) -> dict:
        return summary(project_or_404(pid))

    @app.get("/projects/{pid}/records")
    async def records(pid: str) -> list[dict]:
        project_or_404(pid)
        return store.records(pid)

    @app.get("/projects/{pid}/decisions")
    async def decisions(pid: str) -> list[dict]:
        project_or_404(pid)
        return store.decisions(pid)

    @app.get("/projects/{pid}/gate")
    async def pending_gate(pid: str) -> dict | None:
        project_or_404(pid)
        return store.pending_gate(pid)

    @app.post("/projects/{pid}/gates/{gate_id}/decision")
    async def decide(pid: str, gate_id: str, body: GateDecision) -> dict:
        project_or_404(pid)
        gate = store.get_gate(gate_id)
        if not gate or gate["project_id"] != pid:
            raise HTTPException(404, "gate not found")
        future = gates.get(gate_id)
        if gate["status"] != "pending" or future is None or future.done():
            raise HTTPException(409, "gate is no longer awaiting a decision")
        if body.action in ("modify", "inject") and not (body.payload or "").strip():
            raise HTTPException(422, f"'{body.action}' requires a payload")
        future.set_result(Decision(body.action, (body.payload or "").strip() or None))
        return {"ok": True}

    @app.get("/projects/{pid}/notebook")
    async def notebook(pid: str) -> dict:
        row = project_or_404(pid)
        path = row.get("notebook_path")
        if not path or not Path(path).exists():
            raise HTTPException(404, "notebook not ready")
        return json.loads(Path(path).read_text(encoding="utf-8"))

    @app.get("/projects/{pid}/events")
    async def events(pid: str) -> StreamingResponse:
        """Server-sent events: new provenance records, gate changes, status, running cost."""
        project_or_404(pid)

        async def stream():
            seen, last_gate, last_status = 0, None, None
            while True:
                recs = store.records(pid)
                for r in recs[seen:]:
                    yield f"event: record\ndata: {json.dumps(r)}\n\n"
                seen = len(recs)
                gate = store.pending_gate(pid)
                gate_id = gate["id"] if gate else None
                if gate_id != last_gate:
                    last_gate = gate_id
                    yield f"event: gate\ndata: {json.dumps(gate)}\n\n"
                row = dict(store.get_project(pid))
                if row["status"] != last_status:
                    last_status = row["status"]
                    yield f"event: status\ndata: {json.dumps(summary(row))}\n\n"
                if row["status"] != "running" and gate is None:
                    yield "event: end\ndata: {}\n\n"
                    return
                yield ": keepalive\n\n"
                await asyncio.sleep(0.7)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache"})

    @app.get("/costs")
    async def costs() -> dict:
        return {"total_usd": sum(r["cost_usd"] or 0 for r in store.cost_by_model()),
                "by_model": store.cost_by_model(),
                "projects": [{"id": p["id"], "question": p["question"], "status": p["status"],
                              "cost_usd": store.project_cost(p["id"])}
                             for p in store.list_projects()]}

    @app.get("/strategy")
    async def strategy() -> dict:
        return {"lessons": store.kv_get(LESSONS_KEY, [])}

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True, "running": len(tasks)}

    return app
