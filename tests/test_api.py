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

from .test_pipeline import GOOD, StubExecutor, StubLit, StubRouter

Q = {"question": "Does GC content correlate with mutation rate?"}


def factory_for(tmp_path, auto=False):
    def factory(pid, store, gate, log, executor_kind):
        return Pipeline(router=StubRouter(log), literature=StubLit(log),
                        executor=StubExecutor([GOOD]), store=store, log=log,
                        gate=ScriptedGate([]) if auto else gate,
                        notebook_dir=str(tmp_path), replicates=3)
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

    async def run(self, code, *, args=None, timeout=120):
        raise RuntimeError("503")

    async def checkpoint(self, code): raise RuntimeError("503")
    async def clean_checkpoint(self, code): raise RuntimeError("503")
    async def run_branches(self, ckpt, jobs, **kw): raise RuntimeError("503")

    async def fork(self, b): raise RuntimeError("503")
    async def rollback(self, b=None): raise RuntimeError("503")


async def test_resilient_executor_degrades_and_labels_the_backend():
    ex = ResilientExecutor(Exploding(), StubExecutor([ExecResult("x", "", 0, 0.1, "local-fallback")]))
    r = await ex.run("print(1)")
    assert r.backend == "local-fallback" and ex.degraded
    await ex.fork("b")  # no raise once degraded


async def test_resilient_executor_falls_back_for_branches_too():
    from palissy.sandbox.base import Checkpoint, Job
    fallback = StubExecutor([GOOD])
    ex = ResilientExecutor(Exploding(), fallback)
    ck = await ex.checkpoint("print(1)")  # the primary can't snapshot, so the fallback does
    assert ex.degraded and ck.backend == "stub"
    out = await ex.run_branches(ck, [Job("treatment", 0)])
    assert out[0].result.backend == "stub" and fallback.waves == [(1, False)]
    # a snapshot that came from the primary means nothing to the fallback: it is rebuilt
    other = ResilientExecutor(Exploding(), StubExecutor([GOOD]))
    foreign = Checkpoint(backend="contree", code="print(2)", code_hash="x", image="img")
    out = await other.run_branches(foreign, [Job("negative", 1)])
    assert other.degraded and other.fallback.ran == [("print(2)", "negative", 1)]


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


def finish(client):
    pid = client.post("/projects", json=Q).json()["id"]
    g = None
    for _ in range(3):
        g = next_gate(client, pid, g["id"] if g else None)
        assert decide(client, pid, g, "approve").status_code == 200
    wait_for(lambda: client.get(f"/projects/{pid}").json()["status"] == "done")
    return pid


def test_replay_reruns_the_recorded_runs_and_keeps_the_result(client):
    pid = finish(client)
    assert client.get(f"/projects/{pid}/replay").json() is None
    r = client.post(f"/projects/{pid}/replay")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 9 and body["matched"] == 9 and body["base"] == "tag:stub-base"
    assert client.get(f"/projects/{pid}/replay").json()["matched"] == 9
    assert any(x["stage"] == "replay" for x in client.get(f"/projects/{pid}/records").json())
    st = client.get(f"/projects/{pid}").json()["state"]
    assert len(st["branches"]) == 9 and st["tally"]["treatment"]["hits"] == 3


def test_replay_is_refused_while_running_or_without_runs(client):
    pid = client.post("/projects", json=Q).json()["id"]
    next_gate(client, pid)
    assert client.post(f"/projects/{pid}/replay").status_code == 409  # still running
    assert client.post("/projects/missing/replay").status_code == 404
    assert client.get("/projects/missing/replay").status_code == 404


def test_replay_failure_is_reported_not_hidden(tmp_path):
    def factory(pid, store, gate, log, kind):
        p = Pipeline(router=StubRouter(log), literature=StubLit(log),
                     executor=StubExecutor([GOOD]), store=store, log=log,
                     gate=ScriptedGate([]), notebook_dir=str(tmp_path), replicates=3)

        async def down(*a, **k):
            raise RuntimeError("contree unreachable")
        if kind == "replay-check":
            p.executor.run_branches = down
        return p
    store = Store(":memory:")
    with TestClient(create_app(store, factory)) as c:
        pid = c.post("/projects", json=Q).json()["id"]
        wait_for(lambda: c.get(f"/projects/{pid}").json()["status"] == "done")
        ok = c.post(f"/projects/{pid}/replay")
        assert ok.status_code == 200
        # a sandbox that goes away mid-replay: a 502 with the reason, and no stale result stored
        import palissy.pipeline as pl
        orig = pl.Pipeline.replay

        async def broken(self, state):
            raise RuntimeError("contree unreachable")
        pl.Pipeline.replay = broken
        try:
            bad = c.post(f"/projects/{pid}/replay")
        finally:
            pl.Pipeline.replay = orig
        assert bad.status_code == 502 and "contree unreachable" in bad.json()["detail"]


def test_routing_endpoint_explains_every_stage(client):
    r = client.get("/routing").json()
    stages = {s["stage"]: s for s in r["stages"]}
    assert stages["hypothesis"]["flavor"] == "ultra" and stages["hypothesis"]["reason"]
    assert stages["literature_summary"]["price_in"] < stages["hypothesis"]["price_in"]


def test_health_reports_where_code_will_run(client):
    h = client.get("/health").json()
    assert h["ok"] and h["executor"] in ("contree", "local") and h["timeout_s"] > 0
