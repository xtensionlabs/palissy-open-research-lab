"""Pipeline tests with stubbed model/search clients: gates, storage, repair and notebook."""

import json

import pytest

from palissy.db import Store
from palissy.gates import Decision, ScriptedGate
from palissy.models import Completion
from palissy.pipeline import LESSONS_KEY, Pipeline, PipelineAborted
from palissy.provenance import ProvenanceLog, ProvenanceRecord
from palissy.sandbox.base import ExecResult


class StubRouter:
    """Returns canned output per stage and logs like the real router."""

    def __init__(self, log, code="print('RESULT: supports')"):
        self.log, self.code, self.calls = log, code, []

    async def complete(self, stage, messages, *, parents=None, sources=None, **kw):
        self.calls.append((stage, messages[-1]["content"]))
        text = {
            "literature_summary": "Summary.",
            "hypothesis": json.dumps({"hypothesis": f"H{len(self.calls)}", "prediction": "P",
                                      "rationale": "R", "cited": [1]}),
            "experiment_design": f"```python\n{self.code}\n```",
            "code_generation": "```python\nprint('fixed')\n```",
            "analysis": json.dumps({"verdict": "supports", "findings": "F", "caveats": ["C"]}),
            "reflection": json.dumps({"what_worked": "W", "what_failed": "X",
                                      "lessons": ["keep runs short"], "change_summary": "S"}),
        }[stage]
        rec = self.log.add(ProvenanceRecord(kind="model", stage=stage, summary=text[:40],
                                            cost_usd=0.001, parents=parents or []))
        return Completion(text=text, record=rec)


class StubLit:
    def __init__(self, log):
        self.log = log

    async def search(self, q):
        rec = self.log.add(ProvenanceRecord(kind="search", stage="literature", summary=q))
        return [{"title": "T", "url": "http://x", "content": "c"}], rec


class StubExecutor:
    name = "stub"

    def __init__(self, results):
        self.results, self.ran = list(results), []

    async def run(self, code, *, timeout=120):
        self.ran.append(code)
        return self.results.pop(0)

    async def fork(self, branch): ...
    async def rollback(self, branch=None): ...


OK = ExecResult("RESULT: supports\n", "", 0, 0.1, "stub")
FAIL = ExecResult("", "Traceback: boom", 1, 0.1, "stub")


def make(tmp_path, decisions, results, code="print(1)"):
    store = Store(":memory:")
    pid = store.create_project("q")
    log = ProvenanceLog(store=store, project_id=pid)
    gate = ScriptedGate(decisions)
    ex = StubExecutor(results)
    router = StubRouter(log, code)
    p = Pipeline(router=router, literature=StubLit(log), executor=ex, gate=gate,
                 store=store, log=log, notebook_dir=str(tmp_path))
    return p, store, pid, gate, ex, router


async def test_full_run_records_provenance_decisions_and_notebook(tmp_path):
    p, store, pid, gate, ex, _ = make(tmp_path, [], [OK])
    s = await p.run("q")
    assert s.verdict == "supports" and s.exit_code == 0
    assert [d["stage"] for d in store.decisions(pid)] == [
        "hypothesis", "experiment_design", "strategy_update"]
    kinds = {r["kind"] for r in store.records(pid)}
    assert {"model", "search", "sandbox", "decision"} <= kinds
    assert store.kv_get(LESSONS_KEY) == ["keep runs short"]
    nb = json.loads(open(s.notebook_path, encoding="utf-8").read())
    assert nb["nbformat"] == 4 and any(c["cell_type"] == "code" for c in nb["cells"])
    assert store.get_project(pid)["status"] == "done"


async def test_nothing_executes_before_experiment_approval(tmp_path):
    decisions = [Decision("approve"), Decision("reject", "too big"), Decision("approve")]
    p, store, pid, gate, ex, router = make(tmp_path, decisions, [OK])
    await p.run("q")
    assert len(ex.ran) == 1  # the rejected draft never ran
    designs = [c for c in router.calls if c[0] == "experiment_design"]
    assert len(designs) == 2 and "too big" in designs[1][1]


async def test_inject_reaches_the_regenerated_hypothesis(tmp_path):
    decisions = [Decision("inject", "focus on E. coli"), Decision("approve")]
    p, _, _, _, _, router = make(tmp_path, decisions, [OK])
    await p.run("q")
    hyps = [c for c in router.calls if c[0] == "hypothesis"]
    assert "focus on E. coli" in hyps[1][1] and "focus on E. coli" not in hyps[0][1]


async def test_modify_replaces_the_hypothesis(tmp_path):
    p, _, _, _, ex, _ = make(tmp_path, [Decision("modify", "My own hypothesis")], [OK])
    s = await p.run("q")
    assert s.hypothesis == "My own hypothesis"


async def test_failed_run_is_repaired_then_succeeds(tmp_path):
    p, store, pid, _, ex, _ = make(tmp_path, [], [FAIL, OK])
    s = await p.run("q")
    assert s.repaired and ex.ran[-1] == "print('fixed')"
    assert len(ex.ran) == 2


async def test_failure_after_repair_is_reported_as_failed(tmp_path):
    p, *_ = make(tmp_path, [], [FAIL, FAIL, FAIL])
    s = await p.run("q")
    assert s.verdict == "failed"  # exit code overrides the model's verdict


async def test_repeated_rejection_aborts_and_marks_project_failed(tmp_path):
    p, store, pid, *_ = make(tmp_path, [Decision("reject", "no")] * 3, [OK])
    with pytest.raises(PipelineAborted):
        await p.run("q")
    assert store.get_project(pid)["status"] == "failed"


async def test_lessons_from_one_run_feed_the_next(tmp_path):
    p, store, pid, _, ex, router = make(tmp_path, [], [OK, OK])
    await p.run("q")
    log2 = ProvenanceLog(store=store, project_id=store.create_project("q2"))
    router2 = StubRouter(log2)
    p2 = Pipeline(router=router2, literature=StubLit(log2), executor=StubExecutor([OK]),
                  gate=ScriptedGate([]), store=store, log=log2, notebook_dir=str(tmp_path))
    s2 = await p2.run("q2")
    assert s2.lessons_before == ["keep runs short"]
    assert "keep runs short" in [c for c in router2.calls if c[0] == "hypothesis"][0][1]
