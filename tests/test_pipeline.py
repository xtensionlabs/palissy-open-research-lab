"""Pipeline tests with stubbed model/search clients: gates, storage, repair and notebook."""

import json

import pytest

from palissy.db import Store
from palissy.gates import Decision, ScriptedGate
from palissy.models import Completion
from palissy.pipeline import LESSONS_KEY, Pipeline, PipelineAborted
from palissy.provenance import ProvenanceLog, ProvenanceRecord
from palissy.sandbox.base import ExecResult

CONTRACT = {
    "statistic": "difference in mean fitness", "test": "permutation test, 1000 shuffles",
    "null": "baseline population", "alpha": 0.05, "direction": "increase",
    "supports_if": "p < 0.05 with a positive effect", "refutes_if": "p >= 0.05",
    "positive_control": "fitness +0.5 planted", "negative_control": "second baseline draw",
}


def critic_json(level="ok"):
    ok = level == "ok"
    return json.dumps({"level": level, "summary": "S", "answers": {
        k: {"ok": ok, "why": "because"} for k in
        ("knowable_in_advance", "null_is_real", "test_matches_claim")}})


class StubRouter:
    """Returns canned output per stage and logs like the real router."""

    def __init__(self, log, code="print(1)", *, triage="testable", critic="ok",
                 escalated="ok", contract=CONTRACT, hypothesis=None,
                 reframes=("A real question?",)):
        self.log, self.code, self.calls = log, code, []
        self.reframes = list(reframes)
        self.triage, self.critic, self.escalated = triage, critic, escalated
        self.contract, self.hypothesis = contract, hypothesis

    async def complete(self, stage, messages, *, parents=None, sources=None, **kw):
        self.calls.append((stage, messages[-1]["content"]))
        n_hyp = sum(1 for c in self.calls if c[0] == "hypothesis")
        prereg = f"```json\n{json.dumps(self.contract)}\n```\n" if self.contract else ""
        text = {
            "triage": json.dumps({"category": self.triage, "reason": "R", "reframe": (
                self.reframes.pop(0) if len(self.reframes) > 1 else self.reframes[0])}),
            "literature_summary": "Summary.",
            "hypothesis": json.dumps({
                "hypothesis": (self.hypothesis(n_hyp) if self.hypothesis
                               else f"H{len(self.calls)} increases fitness"),
                "prediction": "P", "rationale": "R", "cited": [1]}),
            "experiment_design": f"{prereg}```python\n{self.code}\n```",
            "design_critic": critic_json(self.critic),
            "design_critic_escalated": ("Let me think step by step..." if self.escalated == "none"
                                        else critic_json(self.escalated)),
            "code_generation": "```python\nprint('fixed')\n```",
            "analysis": json.dumps({"findings": "F", "caveats": ["C"]}),
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


def result_line(arm, effect, p, n=200, successes=None):
    return "RESULT_JSON: " + json.dumps({"arm": arm, "effect": effect, "p_value": p, "n": n,
                                         "successes": successes}) + "\n"


def arms(**by_arm):
    """An executor response per arm: arms(treatment=(0.3, 0.01), ...)."""
    def run(arm):
        return ExecResult(result_line(arm, *by_arm[arm]), "", 0, 0.1, "stub")
    return run


GOOD = arms(treatment=(0.3, 0.01), positive=(0.5, 0.001), negative=(0.02, 0.6))
FAIL = ExecResult("", "Traceback: boom", 1, 0.1, "stub")


class StubExecutor:
    """Each call takes the next item (an ExecResult or arm -> ExecResult); the last repeats."""

    name = "stub"

    def __init__(self, results):
        self.results, self.ran = list(results), []

    async def run(self, code, *, args=None, timeout=120):
        arm = (args or ["treatment"])[0]
        self.ran.append((code, arm))
        item = self.results.pop(0) if len(self.results) > 1 else self.results[0]
        return item(arm) if callable(item) else item

    async def fork(self, branch): ...
    async def rollback(self, branch=None): ...


def make(tmp_path, decisions, results, code="print(1)", **router_kw):
    store = Store(":memory:")
    pid = store.create_project("q")
    log = ProvenanceLog(store=store, project_id=pid)
    gate = ScriptedGate(decisions)
    ex = StubExecutor(results)
    router = StubRouter(log, code, **router_kw)
    p = Pipeline(router=router, literature=StubLit(log), executor=ex, gate=gate,
                 store=store, log=log, notebook_dir=str(tmp_path))
    return p, store, pid, gate, ex, router


async def test_full_run_records_provenance_decisions_and_notebook(tmp_path):
    p, store, pid, gate, ex, _ = make(tmp_path, [], [GOOD])
    s = await p.run("q")
    assert s.verdict == "supports" and s.exit_code == 0 and s.verdict_reasons == []
    assert [d["stage"] for d in store.decisions(pid)] == [
        "hypothesis", "experiment_design", "strategy_update"]
    kinds = {r["kind"] for r in store.records(pid)}
    assert {"model", "search", "sandbox", "decision", "rule"} <= kinds
    assert store.kv_get(LESSONS_KEY) == ["keep runs short"]
    nb = json.loads(open(s.notebook_path, encoding="utf-8").read())
    assert nb["nbformat"] == 4 and any(c["cell_type"] == "code" for c in nb["cells"])
    text = "".join("".join(c["source"]) for c in nb["cells"])
    assert "Pre-registration" in text and s.contract_hash in text
    assert store.get_project(pid)["status"] == "done"


async def test_every_arm_runs_and_the_verdict_is_computed_not_asked(tmp_path):
    p, store, pid, _, ex, router = make(tmp_path, [], [GOOD])
    s = await p.run("q")
    assert [a for _, a in ex.ran] == ["treatment", "positive", "negative"]
    assert set(s.arms) == {"treatment", "positive", "negative"}
    rule = [r for r in store.records(pid) if r["kind"] == "rule" and r["stage"] == "analysis"][0]
    assert rule["outputs"]["verdict"] == "supports"
    assert set(rule["parents"]) == {o["record_id"] for o in s.arms.values()}
    # the analyst is told the verdict; nothing it says can change it
    assert "Verdict: supports" in [c for c in router.calls if c[0] == "analysis"][0][1]


async def test_the_hulk_run_is_inconclusive_not_supports(tmp_path):
    """0.001 mutations x 1e5 generations vs a 1e6 threshold: 0 of 2000 in every arm, p = 1."""
    rigged = arms(treatment=(0.0, 1.0, 2000, 0), positive=(0.0, 1.0, 2000, 0),
                  negative=(0.0, 1.0, 2000, 0))
    p, *_ = make(tmp_path, [], [rigged])
    s = await p.run("Is Hulk's DNA possible to achieve?")
    assert s.verdict == "inconclusive"
    text = " ".join(s.verdict_reasons)
    assert "planted on purpose" in text and "fixed by the parameters" in text
    assert s.what_failed.startswith("Result unusable:")


async def test_no_preregistration_means_no_verdict(tmp_path):
    p, _, _, _, _, router = make(tmp_path, [], [GOOD], contract=None)
    s = await p.run("q")
    assert s.verdict == "inconclusive" and s.contract == {}
    assert len([c for c in router.calls if c[0] == "experiment_design"]) == 2  # one retry
    assert "pre-registration" in [c for c in router.calls
                                  if c[0] == "experiment_design"][1][1]


async def test_tampered_preregistration_is_caught(tmp_path):
    p, *_ = make(tmp_path, [], [GOOD])
    orig = p.analysis_stage

    async def tamper(s):
        s.contract = {**s.contract, "alpha": 0.2}
        await orig(s)
    p.analysis_stage = tamper
    s = await p.run("q")
    assert s.verdict == "inconclusive" and "changed after you approved" in s.verdict_reasons[0]


async def test_critic_runs_before_the_gate_and_escalates_only_on_concern(tmp_path):
    p, _, _, gate, _, router = make(tmp_path, [], [GOOD])
    await p.run("q")
    stages = [c[0] for c in router.calls]
    assert "design_critic" in stages and "design_critic_escalated" not in stages
    design_view = [v for st, v in gate.seen if st == "experiment_design"][0]
    assert design_view["critic"]["level"] == "ok"
    assert design_view["preregistration"]["alpha"] == 0.05

    p2, _, _, gate2, _, router2 = make(tmp_path, [], [GOOD], critic="blocking",
                                       escalated="blocking")
    await p2.run("q")
    assert [c[0] for c in router2.calls].count("design_critic_escalated") == 1
    view = [v for st, v in gate2.seen if st == "experiment_design"][0]
    assert view["critic"]["checked_by"] == ["super", "ultra"]


async def test_escalated_critic_without_an_answer_keeps_the_first_objection(tmp_path):
    p, _, _, gate, _, _ = make(tmp_path, [], [GOOD], critic="blocking", escalated="none")
    s = await p.run("q")
    view = [v for st, v in gate.seen if st == "experiment_design"][0]
    assert view["critic"]["level"] == "blocking"
    assert view["critic"]["checked_by"] == ["super", "ultra (no answer)"]
    # approving anyway is recorded, and the verdict is still the rule's, not the critic's
    assert s.critique["approved_over"] == "blocking" and s.verdict == "supports"


async def test_a_cut_off_json_reply_is_asked_for_again(tmp_path):
    p, _, _, _, _, router = make(tmp_path, [], [GOOD])
    real = router.complete
    cut = {"n": 0}

    async def flaky(stage, messages, **kw):
        if stage == "reflection" and cut["n"] == 0:
            cut["n"] += 1
            rec = router.log.add(ProvenanceRecord(kind="model", stage=stage, summary=""))
            return Completion('{"what_worked": "The experiment ran and', rec)
        return await real(stage, messages, **kw)
    router.complete = flaky
    s = await p.run("q")
    assert s.lessons_after == ["keep runs short"]
    assert "cut off" in [c for c in router.calls if c[0] == "reflection"][-1][1]


async def test_triage_asks_again_when_the_reframe_is_missing(tmp_path):
    p, _, _, gate, _, router = make(tmp_path, [Decision("approve")], [GOOD], triage="fiction",
                                    reframes=("", "Does myostatin loss raise muscle mass?"))
    s = await p.run("Is Hulk's DNA possible?")
    assert [c[0] for c in router.calls].count("triage") == 2
    assert s.triage["reframe"].startswith("Does myostatin")


async def test_critic_notes_feed_the_redesign_after_a_reject(tmp_path):
    decisions = [Decision("approve"), Decision("reject", "fix the null"), Decision("approve")]
    p, _, _, _, _, router = make(tmp_path, decisions, [GOOD], critic="concern",
                                 escalated="concern")
    await p.run("q")
    designs = [c for c in router.calls if c[0] == "experiment_design"]
    assert "Design critic (concern)" in designs[1][1] and "fix the null" in designs[1][1]


async def test_unfalsifiable_hypothesis_is_rewritten_once_then_flagged(tmp_path):
    p, _, _, gate, _, router = make(
        tmp_path, [], [GOOD], hypothesis=lambda n: "Humans cannot reach Hulk-level strength")
    s = await p.run("q")
    assert [c[0] for c in router.calls].count("hypothesis") == 2
    assert "cannot" in s.hypothesis_warning
    assert "warning" in [v for st, v in gate.seen if st == "hypothesis"][0]

    p2, _, _, _, _, r2 = make(tmp_path, [], [GOOD], hypothesis=lambda n: (
        "Muscle mass never exceeds X" if n == 1 else "Myostatin loss increases muscle mass"))
    s2 = await p2.run("q")
    assert [c[0] for c in r2.calls].count("hypothesis") == 2 and not s2.hypothesis_warning


async def test_testable_questions_skip_the_triage_gate(tmp_path):
    p, store, pid, gate, *_ = make(tmp_path, [], [GOOD])
    s = await p.run("q")
    assert s.triage["category"] == "testable" and "triage" not in [st for st, _ in gate.seen]


async def test_fiction_is_flagged_and_can_be_reframed(tmp_path):
    p, store, pid, gate, _, router = make(
        tmp_path, [Decision("modify", "Does myostatin loss raise muscle mass in a model?")],
        [GOOD], triage="fiction")
    s = await p.run("Is Hulk's DNA possible?")
    assert gate.seen[0][0] == "triage" and gate.seen[0][1]["category"] == "fiction"
    assert s.original_question == "Is Hulk's DNA possible?"
    assert s.question.startswith("Does myostatin") and s.triage["decision"] == "reframed"
    assert "myostatin" in [c for c in router.calls if c[0] == "hypothesis"][0][1]


async def test_fiction_can_be_continued_knowingly(tmp_path):
    p, *_ = make(tmp_path, [Decision("approve")], [GOOD], triage="fiction")
    s = await p.run("Is Hulk's DNA possible?")
    assert s.question == "Is Hulk's DNA possible?" and s.triage["decision"] == "continued"
    assert s.triage["category"] == "fiction"  # the label stays on the project


async def test_nothing_executes_before_experiment_approval(tmp_path):
    decisions = [Decision("approve"), Decision("reject", "too big"), Decision("approve")]
    p, store, pid, gate, ex, router = make(tmp_path, decisions, [GOOD])
    await p.run("q")
    assert len(ex.ran) == 3  # the rejected draft never ran; the approved one ran once per arm
    designs = [c for c in router.calls if c[0] == "experiment_design"]
    assert len(designs) == 2 and "too big" in designs[1][1]


async def test_inject_reaches_the_regenerated_hypothesis(tmp_path):
    decisions = [Decision("inject", "focus on E. coli"), Decision("approve")]
    p, _, _, _, _, router = make(tmp_path, decisions, [GOOD])
    await p.run("q")
    hyps = [c for c in router.calls if c[0] == "hypothesis"]
    assert "focus on E. coli" in hyps[1][1] and "focus on E. coli" not in hyps[0][1]


async def test_modify_replaces_the_hypothesis(tmp_path):
    p, _, _, _, ex, _ = make(tmp_path, [Decision("modify", "My own hypothesis")], [GOOD])
    s = await p.run("q")
    assert s.hypothesis == "My own hypothesis"


async def test_failed_run_is_repaired_then_succeeds(tmp_path):
    p, store, pid, _, ex, _ = make(tmp_path, [], [FAIL, GOOD])
    s = await p.run("q")
    assert s.repaired and ex.ran[-1] == ("print('fixed')", "negative")
    assert len(ex.ran) == 4  # the broken treatment arm stops the round; then all three arms
    assert s.verdict == "supports"


async def test_missing_result_line_triggers_a_repair(tmp_path):
    silent = ExecResult("done\n", "", 0, 0.1, "stub")
    p, _, _, _, ex, router = make(tmp_path, [], [silent, silent, silent, GOOD])
    s = await p.run("q")
    repair = [c for c in router.calls if c[0] == "code_generation"][0][1]
    assert "RESULT_JSON" in repair and s.repaired


async def test_failure_after_repair_is_reported_as_failed(tmp_path):
    p, *_ = make(tmp_path, [], [FAIL])
    s = await p.run("q")
    assert s.verdict == "failed"  # exit code overrides everything


async def test_repeated_rejection_aborts_and_marks_project_failed(tmp_path):
    p, store, pid, *_ = make(tmp_path, [Decision("reject", "no")] * 3, [GOOD])
    with pytest.raises(PipelineAborted):
        await p.run("q")
    assert store.get_project(pid)["status"] == "failed"


async def test_lessons_from_one_run_feed_the_next(tmp_path):
    p, store, pid, _, ex, router = make(tmp_path, [], [GOOD])
    await p.run("q")
    log2 = ProvenanceLog(store=store, project_id=store.create_project("q2"))
    router2 = StubRouter(log2)
    p2 = Pipeline(router=router2, literature=StubLit(log2), executor=StubExecutor([GOOD]),
                  gate=ScriptedGate([]), store=store, log=log2, notebook_dir=str(tmp_path))
    s2 = await p2.run("q2")
    assert s2.lessons_before == ["keep runs short"]
    assert "keep runs short" in [c for c in router2.calls if c[0] == "hypothesis"][0][1]
