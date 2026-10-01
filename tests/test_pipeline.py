"""Pipeline tests with stubbed model/search clients: gates, storage, repair and notebook."""

import json

import pytest

from palissy.db import Store
from palissy.gates import Decision, ScriptedGate
from palissy.models import Completion
from palissy.pipeline import LESSONS_KEY, Pipeline, PipelineAborted
from palissy.provenance import ProvenanceLog, ProvenanceRecord
from palissy.sandbox.base import Branch, Checkpoint, ExecResult, sha

CONTRACT = {
    "statistic": "difference in mean fitness", "test": "permutation test, 1000 shuffles",
    "null": "baseline population", "alpha": 0.05, "direction": "increase",
    "supports_if": "p < 0.05 with a positive effect", "refutes_if": "p >= 0.05",
    "positive_control": "fitness +0.5 planted", "negative_control": "second baseline draw",
}
QUESTIONS = ("knowable_in_advance", "null_is_real", "effect_not_typed_in",
             "test_matches_claim")
REPS = 3  # seeds per arm in these tests: 9 branches, quorum of 2 per arm


def critic_json(level="ok"):
    ok = level == "ok"
    return json.dumps({"level": level, "summary": "S", "answers": {
        k: {"ok": ok, "why": "because"} for k in QUESTIONS}})


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
    """A response per branch: arms(treatment=(effect, p[, n, successes]), ...). A value may be
    a list of such tuples, one per replicate (cycled)."""
    def respond(job):
        v = by_arm[job.arm]
        spec = v[job.rep % len(v)] if isinstance(v, list) else v
        return ExecResult(result_line(job.arm, *spec), "", 0, 0.1, "stub", op_id=f"op-{job.label}")
    return respond


GOOD = arms(treatment=(0.3, 0.01), positive=(0.5, 0.001), negative=(0.02, 0.6))
FAIL = ExecResult("", "Traceback: boom", 1, 0.1, "stub")


class StubExecutor:
    """Each branch takes the next item (an ExecResult or job -> ExecResult); the last repeats."""

    name = "stub"

    def __init__(self, results):
        self.results, self.ran, self.waves, self.checkpoints = list(results), [], [], []

    def _next(self, job):
        item = self.results.pop(0) if len(self.results) > 1 else self.results[0]
        return item(job) if callable(item) else item

    async def checkpoint(self, code):
        self.checkpoints.append(code)
        return Checkpoint("stub", code, sha(code), image=f"img-{sha(code)[:6]}",
                          base="tag:stub-base")

    async def clean_checkpoint(self, code):
        return Checkpoint("stub", code, sha(code), base="tag:stub-base")

    async def run_branches(self, ckpt, jobs, *, concurrency=4, timeout=120, clean=False):
        self.waves.append((len(jobs), clean))
        out = []
        for j in jobs:
            self.ran.append((ckpt.code, j.arm, j.rep))
            out.append(Branch(j, self._next(j), key=f"b{len(self.ran)}"))
        return out

    async def run(self, code, *, args=None, timeout=120):
        self.ran.append((code, (args or ["treatment"])[0], 0))
        return self.results[0]

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
                 store=store, log=log, notebook_dir=str(tmp_path), replicates=REPS)
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
    assert "harness.py" in text and "treatment#1" in text and "Positive control" in text
    assert store.get_project(pid)["status"] == "done"


async def test_arms_fork_from_one_checkpoint_and_the_verdict_is_computed_not_asked(tmp_path):
    p, store, pid, _, ex, router = make(tmp_path, [], [GOOD])
    s = await p.run("q")
    assert ex.waves == [(1, False), (8, False)]  # one run alone, then the other eight in parallel
    assert ex.ran[0][1:] == ("treatment", 0) and len(ex.ran) == 9
    assert len(ex.checkpoints) == 1 and s.checkpoint["image"].startswith("img-")
    assert len(s.branches) == 9 and {b["status"] for b in s.branches} == {"kept"}
    assert [b["seed_offset"] for b in s.branches if b["arm"] == "negative"] == [0, 1009, 2018]
    recs = store.records(pid)
    ck = [r for r in recs if r["stage"] == "checkpoint"][0]
    runs = [r for r in recs if r["kind"] == "sandbox" and r["stage"] == "execution"]
    assert len(runs) == 9 and all(ck["id"] in r["parents"] for r in runs)
    assert runs[1]["inputs"]["seed_offset"] == 0 and runs[3]["inputs"]["rep"] == 1
    rule = [r for r in recs if r["kind"] == "rule" and r["stage"] == "analysis"][0]
    assert rule["outputs"]["verdict"] == "supports"
    assert set(rule["parents"]) == {r["id"] for r in runs}
    assert s.tally["treatment"] == {"total": 3, "ok": 3, "hits": 3, "median_effect": 0.3,
                                    "median_p": 0.01}
    for arm, hits in (("treatment", 3), ("positive", 3), ("negative", 0)):
        assert sum(b["hit"] for b in s.branches if b["arm"] == arm) == hits == (
            s.tally[arm]["hits"])
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


async def test_a_noisy_single_seed_no_longer_voids_the_run(tmp_path):
    """Run 3ce59d2e: one fixed seed made the negative arm fire (p=0.003) and the whole run was
    thrown away. Across seeds that is one false alarm in three: within what alpha allows."""
    contract = {**CONTRACT, "alpha": 0.01, "direction": "decrease"}
    noisy = arms(treatment=(-0.3, 0.0001), positive=(-0.5, 0.0001),
                 negative=[(-0.075, 0.003), (0.01, 0.6), (0.0, 0.8)])
    p, *_ = make(tmp_path, [], [noisy], contract=contract)
    s = await p.run("q")
    assert s.verdict == "supports" and s.tally["negative"]["hits"] == 1
    check = next(c for c in s.checks if c["name"] == "Negative control")
    assert check["passed"] and check["detail"].startswith("False alarm in 1 of 3")


async def test_a_boundary_treatment_is_inconclusive_across_seeds(tmp_path):
    flips = arms(treatment=[(0.3, 0.01), (0.02, 0.6), (0.02, 0.5)],
                 positive=(0.5, 0.001), negative=(0.02, 0.6))
    p, *_ = make(tmp_path, [], [flips])
    s = await p.run("q")
    assert s.verdict == "inconclusive" and "changes with the seed" in s.verdict_reasons[-1]


async def test_failed_branches_are_rolled_back_and_survivors_decide(tmp_path):
    def one_bad(job):
        if job.arm == "treatment" and job.rep == 2:
            return FAIL
        return GOOD(job)
    p, store, pid, *_ = make(tmp_path, [], [one_bad])
    s = await p.run("q")
    assert s.verdict == "supports" and not s.repaired  # one dead seed is not a broken script
    bad = [b for b in s.branches if b["status"] == "rolled_back"]
    assert [(b["id"], b["reason"]) for b in bad] == [("treatment#3", "exit 1")]
    assert s.tally["treatment"]["ok"] == 2 and s.exit_code == 1


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
    assert len(ex.ran) == 9  # the rejected draft never ran; the approved one ran 3 arms x 3 seeds
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


async def test_a_broken_script_fails_once_then_is_repaired_before_the_fan_out(tmp_path):
    p, store, pid, _, ex, _ = make(tmp_path, [], [FAIL, GOOD])
    s = await p.run("q")
    assert s.repaired and ex.ran[-1][0] == "print('fixed')"
    assert ex.waves == [(1, False), (1, False), (8, False)]  # not 9 crashes: one, then repair
    assert len(ex.checkpoints) == 2 and ex.checkpoints[1] == "print('fixed')"
    assert s.verdict == "supports"


async def test_missing_result_line_triggers_a_repair(tmp_path):
    silent = ExecResult("done\n", "", 0, 0.1, "stub")
    p, _, _, _, ex, router = make(tmp_path, [], [silent, GOOD])
    s = await p.run("q")
    repair = [c for c in router.calls if c[0] == "code_generation"][0][1]
    assert "RESULT_JSON" in repair and s.repaired


async def test_failure_after_repair_is_reported_as_failed(tmp_path):
    p, *_ = make(tmp_path, [], [FAIL])
    s = await p.run("q")
    assert s.verdict == "failed"  # a script that never runs can't be read, whatever the model says
    assert len(p.executor.checkpoints) == 3  # first try plus two repairs


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
                  gate=ScriptedGate([]), store=store, log=log2, notebook_dir=str(tmp_path),
                  replicates=REPS)
    s2 = await p2.run("q2")
    assert s2.lessons_before == ["keep runs short"]
    assert "keep runs short" in [c for c in router2.calls if c[0] == "hypothesis"][0][1]


# --- replay -------------------------------------------------------------------------------


def saved_state(store, pid):
    return json.loads(store.get_project(pid)["state"])


async def test_replay_reruns_every_branch_clean_and_matches(tmp_path):
    p, store, pid, _, ex, _ = make(tmp_path, [], [GOOD])
    await p.run("q")
    out = await p.replay(saved_state(store, pid))
    assert out["total"] == 9 and out["matched"] == 9 and out["base"] == "tag:stub-base"
    assert ex.waves[-1] == (9, True)  # one wave, all from the clean base, not the checkpoint
    assert all(i["match"] for i in out["items"])
    rec = [r for r in store.records(pid) if r["stage"] == "replay"][0]
    assert rec["kind"] == "rule" and rec["outputs"]["matched"] == 9
    assert len(rec["parents"]) == 9
    assert store.kv_get(f"replay:{pid}")["matched"] == 9


async def test_replay_reports_a_mismatch_instead_of_hiding_it(tmp_path):
    p, store, pid, _, ex, _ = make(tmp_path, [], [GOOD])
    await p.run("q")
    ex.results = [arms(treatment=(0.31, 0.01), positive=(0.5, 0.001), negative=(0.02, 0.6))]
    out = await p.replay(saved_state(store, pid))
    assert out["matched"] == 6 and out["total"] == 9
    assert {i["id"] for i in out["items"] if not i["match"]} == {
        "treatment#1", "treatment#2", "treatment#3"}


async def test_replay_needs_recorded_runs(tmp_path):
    p, *_ = make(tmp_path, [], [GOOD])
    with pytest.raises(ValueError, match="no recorded runs"):
        await p.replay({"branches": [], "code": "print(1)"})
