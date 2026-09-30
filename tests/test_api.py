"""API tests: real HTTP through TestClient, stubbed model/search/executor."""

import json
import time

import pytest
from fastapi.testclient import TestClient

from palissy.api import create_app
from palissy.db import Store
from palissy.gates import ScriptedGate
from palissy.pipeline import Pipeline
from palissy.provenance import ProvenanceLog
from palissy.sandbox.base import ExecResult
from palissy.sandbox.resilient import ResilientExecutor

from .test_pipeline import OK, StubExecutor, StubLit, StubRouter

Q = {"question": "Does GC content correlate with mutation rate?"}


def factory_for(tmp_path, auto=False):
    def factory(pid, store, gate, log, executor_kind):
        return Pipeline(router=StubRouter(log), literature=StubLit(log),
                        executor=StubExecutor([OK]), store=store, log=log,
                        gate=ScriptedGate([]) if auto else gate,
                        notebook_dir=str(tmp_path))
    return factory


def wait_for(fn, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        value = fn()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("timed out waiting")


@pytest.fixture
def client(tmp_path):
    app = create_app(Store(":memory:"), factory_for(tmp_path))
    with TestClient(app) as c:
        yield c


def next_gate(client, pid, not_id=None):
    def check():
        g = client.get(f"/projects/{pid}/gate").json()
        return g if g and g["id"] != not_id else None
    return wait_for(check)


def decide(client, pid, gate, action, payload=None):
    return client.post(f"/projects/{pid}/gates/{gate['id']}/decision",
                       json={"action": action, "payload": payload})


def test_full_run_through_http(client):
    pid = client.post("/projects", json=Q).json()["id"]
    stages = []
    for _ in range(3):
        g = next_gate(client, pid, stages[-1]["id"] if stages else None)
        stages.append(g)
        assert decide(client, pid, g, "approve").status_code == 200
    assert [g["stage"] for g in stages] == ["hypothesis", "experiment_design", "strategy_update"]
    wait_for(lambda: client.get(f"/projects/{pid}").json()["status"] == "done")

    assert client.get(f"/projects/{pid}/notebook").json()["nbformat"] == 4
    assert len(client.get(f"/projects/{pid}/decisions").json()) == 3
    assert client.get(f"/projects/{pid}/records").json()
    assert client.get("/costs").json()["total_usd"] > 0
    assert client.get("/strategy").json()["lessons"] == ["keep runs short"]


def test_gate_blocks_until_a_human_decides(client):
    pid = client.post("/projects", json=Q).json()["id"]
    g = next_gate(client, pid)
    time.sleep(0.5)
    p = client.get(f"/projects/{pid}").json()
    assert p["status"] == "running" and p["pending_gate"]["id"] == g["id"]
    assert client.get(f"/projects/{pid}/records").json()  # literature already done
    assert not any(r["stage"] == "experiment_design"
                   for r in client.get(f"/projects/{pid}/records").json())


def test_inject_regenerates_and_creates_a_new_gate(client):
    pid = client.post("/projects", json=Q).json()["id"]
    first = next_gate(client, pid)
    assert decide(client, pid, first, "inject", "focus on E. coli").status_code == 200
    second = next_gate(client, pid, first["id"])
    assert second["stage"] == "hypothesis"
    assert second["proposal"]["hypothesis"] != first["proposal"]["hypothesis"]


def test_modify_needs_a_payload_and_unknown_gate_404(client):
    pid = client.post("/projects", json=Q).json()["id"]
    g = next_gate(client, pid)
    assert decide(client, pid, g, "modify").status_code == 422
    assert decide(client, pid, g, "inject", "   ").status_code == 422
    assert client.post(f"/projects/{pid}/gates/nope/decision",
                       json={"action": "approve"}).status_code == 404
    assert client.post(f"/projects/{pid}/gates/{g['id']}/decision",
                       json={"action": "explode"}).status_code == 422
    assert client.get(f"/projects/{pid}").json()["pending_gate"]["id"] == g["id"]


def test_a_gate_cannot_be_decided_twice(client):
    pid = client.post("/projects", json=Q).json()["id"]
    g = next_gate(client, pid)
    assert decide(client, pid, g, "approve").status_code == 200
    assert decide(client, pid, g, "approve").status_code == 409


def test_gate_of_another_project_is_rejected(client):
    a = client.post("/projects", json=Q).json()["id"]
    b = client.post("/projects", json=Q).json()["id"]
    g = next_gate(client, a)
    assert client.post(f"/projects/{b}/gates/{g['id']}/decision",
                       json={"action": "approve"}).status_code == 404


def test_validation_and_404s(client):
    assert client.post("/projects", json={"question": "hi"}).status_code == 422
    assert client.get("/projects/missing").status_code == 404
    assert client.get("/projects/missing/notebook").status_code == 404


def test_event_stream_ends_with_records_status_and_end(tmp_path):
    app = create_app(Store(":memory:"), factory_for(tmp_path, auto=True))
    with TestClient(app) as c:
        pid = c.post("/projects", json=Q).json()["id"]
        with c.stream("GET", f"/projects/{pid}/events") as r:
            body = "".join(r.iter_text())
    assert "event: record" in body and "event: status" in body
    assert body.rstrip().endswith("event: end\ndata: {}")
    statuses = [json.loads(line[6:])["status"] for line in body.splitlines()
                if line.startswith("data: {") and '"status"' in line and '"question"' in line]
    assert statuses[-1] == "done"


def test_pipeline_failure_is_reported_on_the_project(tmp_path):
    def boom(*a):
        raise RuntimeError("no sandbox")
    app = create_app(Store(":memory:"), boom)
    with TestClient(app) as c:
        pid = c.post("/projects", json=Q).json()["id"]
        p = wait_for(lambda: (x := c.get(f"/projects/{pid}").json())["status"] == "failed" and x)
    assert "no sandbox" in p["error"]


def test_restart_marks_orphaned_runs_interrupted(tmp_path):
    store = Store(":memory:")
    pid = store.create_project("orphan question")
    store.create_gate(pid, 1, "hypothesis", "H", {"x": 1})
    with TestClient(create_app(store, factory_for(tmp_path))) as c:
        p = c.get(f"/projects/{pid}").json()
        assert p["status"] == "interrupted" and p["pending_gate"] is None


class Exploding:
    name = "contree"

    async def run(self, code, *, timeout=120):
        raise RuntimeError("503")

    async def fork(self, b): raise RuntimeError("503")
    async def rollback(self, b=None): raise RuntimeError("503")


async def test_resilient_executor_degrades_and_labels_the_backend():
    ex = ResilientExecutor(Exploding(), StubExecutor([ExecResult("x", "", 0, 0.1, "local-fallback")]))
    r = await ex.run("print(1)")
    assert r.backend == "local-fallback" and ex.degraded
    await ex.fork("b")  # no raise once degraded


def test_state_snapshot_tracks_stage_and_content(client):
    pid = client.post("/projects", json=Q).json()["id"]
    g = next_gate(client, pid)
    p = client.get(f"/projects/{pid}").json()
    assert p["state"]["stage"] == "hypothesis" and p["state"]["literature_summary"]
    assert decide(client, pid, g, "approve").status_code == 200
    g2 = next_gate(client, pid, g["id"])
    assert client.get(f"/projects/{pid}").json()["state"]["hypothesis"]  # approved, persisted
    assert decide(client, pid, g2, "approve").status_code == 200
    g3 = next_gate(client, pid, g2["id"])
    assert decide(client, pid, g3, "approve").status_code == 200
    done = wait_for(lambda: (x := client.get(f"/projects/{pid}").json())["status"] == "done" and x)
    st = done["state"]
    assert st["stage"] == "done" and st["verdict"] == "supports"
    assert st["data_source"] == "simulated" and st["lessons_after"] == ["keep runs short"]


def test_project_list_omits_heavy_state_but_detail_has_it(client):
    pid = client.post("/projects", json=Q).json()["id"]
    next_gate(client, pid)
    assert "state" not in client.get("/projects").json()[0]
    assert "state" in client.get(f"/projects/{pid}").json()


def test_routing_endpoint_explains_every_stage(client):
    r = client.get("/routing").json()
    stages = {s["stage"]: s for s in r["stages"]}
    assert stages["hypothesis"]["flavor"] == "ultra" and stages["hypothesis"]["reason"]
    assert stages["literature_summary"]["price_in"] < stages["hypothesis"]["price_in"]


def test_health_reports_where_code_will_run(client):
    h = client.get("/health").json()
    assert h["ok"] and h["executor"] in ("contree", "local") and h["timeout_s"] > 0
