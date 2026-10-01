"""The pipeline with human gates.

triage -> literature -> hypothesis -> experiment_design -> execution -> analysis -> reflection
-> notebook

Gates sit at triage (only when the question isn't testable), hypothesis, experiment design
(before anything executes), and the strategy update. Every model/tool call and every human
decision lands in the provenance log. The verdict is computed by rule from the pre-registration,
not by a model.
"""

import hashlib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

from .db import Store
from .gates import Decision, Gate
from .literature import Literature
from .models import ModelRouter
from .notebook import build_notebook, write_notebook
from .provenance import ProvenanceLog, ProvenanceRecord
from .sandbox import Executor, log_execution
from .stages.analysis import analyse, reflect
from .stages.critic import Critique, critique
from .stages.hypothesis import (Design, Hypothesis, design_experiment, propose_hypothesis,
                                repair_experiment)
from .stages.triage import triage
from .stages.verdict import ARMS, Check, Contract, Verdict, decide, parse_result

MAX_ATTEMPTS = 3
MAX_REPAIRS = 2
LESSONS_KEY = "strategy_lessons"


class PipelineAborted(RuntimeError):
    pass


@dataclass
class CycleState:
    question: str
    stage: str = "triage"
    original_question: str = ""
    triage: dict = field(default_factory=dict)
    data_source: str = "simulated"  # experiments are pure simulations (no external datasets)
    lessons_before: list[str] = field(default_factory=list)
    lessons_after: list[str] = field(default_factory=list)
    human_notes: list[str] = field(default_factory=list)
    literature: list[dict] = field(default_factory=list)
    literature_summary: str = ""
    lit_record_id: str = ""
    hypothesis: str = ""
    prediction: str = ""
    rationale: str = ""
    hypothesis_warning: str = ""
    hypothesis_record_id: str = ""
    code: str = ""
    code_record_id: str = ""
    contract: dict = field(default_factory=dict)  # frozen pre-registration ({} if none)
    contract_error: str = ""
    contract_hash: str = ""
    code_hash: str = ""  # of the approved code; a crash repair changes the code, not this
    critique: dict = field(default_factory=dict)
    backend: str = ""
    arms: dict = field(default_factory=dict)  # arm -> stdout/stderr/exit_code/result/record_id
    stdout: str = ""
    stderr: str = ""
    exit_code: int = -1
    exec_record_id: str = ""
    repaired: bool = False
    verdict: str = ""
    verdict_reasons: list[str] = field(default_factory=list)
    checks: list[dict] = field(default_factory=list)
    verdict_record_id: str = ""
    findings: str = ""
    caveats: list[str] = field(default_factory=list)
    analysis_record_id: str = ""
    what_worked: str = ""
    what_failed: str = ""
    change_summary: str = ""
    notebook_path: str = ""

    def notes(self) -> str:
        parts = [f"- {l}" for l in self.lessons_before] + [f"- Researcher: {n}"
                                                            for n in self.human_notes]
        return "\n".join(parts)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def arm_problem(arms: dict[str, dict]) -> str | None:
    """What a repair pass should fix, or None if every arm ran and reported a result."""
    for arm in ARMS:
        o = arms.get(arm)
        if o is None:
            continue  # not reached because an earlier arm failed
        if o["exit_code"] != 0:
            return f"[{arm} arm] exit {o['exit_code']}\n{o['stderr'] or o['stdout']}"
        if o["result"] is None:
            return (f"[{arm} arm] finished but printed no valid RESULT_JSON line as its last "
                    f"line. Output tail:\n{o['stdout'][-800:]}")
    return None


class Pipeline:
    def __init__(self, *, router: ModelRouter, literature: Literature, executor: Executor,
                 gate: Gate, store: Store, log: ProvenanceLog, notebook_dir: str = "notebooks"):
        self.router, self.lit, self.executor = router, literature, executor
        self.gate, self.store, self.log = gate, store, log
        self.notebook_dir = notebook_dir

    def _save(self, s: CycleState) -> None:
        self.store.save_state(self.log.project_id, asdict(s))

    async def _decide(self, stage: str, title: str, proposal: dict, parent_id: str) -> Decision:
        d = await self.gate.review(stage, title, proposal)
        self.store.add_decision(self.log.project_id, self.log.cycle, stage, proposal,
                                d.action, d.payload)
        self.log.add(ProvenanceRecord(
            kind="decision", stage=stage, summary=f"human: {d.action}",
            inputs=proposal, outputs={"action": d.action, "payload": d.payload},
            parents=[parent_id]))
        return d

    async def _gated(self, stage: str, title: str, generate: Callable[[], Awaitable[dict]],
                     state: CycleState, apply_modify: Callable[[dict, str], dict],
                     parent_id: Callable[[dict], str]) -> dict:
        """Generate, ask a human, and regenerate on reject/inject until approved."""
        for _ in range(MAX_ATTEMPTS):
            proposal = await generate()
            d = await self._decide(stage, title, proposal["view"], parent_id(proposal))
            if d.action == "approve":
                return proposal
            if d.action == "modify" and d.payload:
                return apply_modify(proposal, d.payload)
            if d.action == "inject" and d.payload:
                state.human_notes.append(d.payload)
            elif d.action == "reject":
                state.human_notes.append(f"Rejected previous {stage}: {d.payload or 'no reason'}")
            self._save(state)
        raise PipelineAborted(f"No approved {stage} after {MAX_ATTEMPTS} attempts")

    # --- stages -------------------------------------------------------------------------

    async def triage_stage(self, s: CycleState) -> None:
        """Say plainly when a question is fiction or untestable; the researcher decides."""
        s.original_question = s.original_question or s.question
        for _ in range(MAX_ATTEMPTS):
            t = await triage(self.router, s.question, "\n".join(s.human_notes))
            s.triage = t.as_view(s.question)
            if t.testable:
                return
            self._save(s)
            d = await self._decide("triage", "Is this question testable?", s.triage, t.record_id)
            if d.action == "approve":
                s.triage["decision"] = "continued"
                return
            if d.action == "modify" and d.payload:
                s.question = d.payload
                s.triage["decision"] = "reframed"
                return
            s.human_notes.append(d.payload or "Rejected the triage")  # inject/reject: re-triage
        raise PipelineAborted(f"No decision on the question after {MAX_ATTEMPTS} attempts")

    async def literature_stage(self, s: CycleState) -> None:
        results, rec = await self.lit.search(s.question)
        s.literature, s.lit_record_id = results, rec.id
        excerpts = "\n\n".join(f"{r['title']}: {(r.get('content') or '')[:800]}" for r in results)
        out = await self.router.complete(
            "literature_summary",
            [{"role": "user", "content": "Summarise the state of knowledge relevant to this "
              f"question in 4-6 sentences.\nQuestion: {s.question}\n\n{excerpts}"}],
            max_tokens=1500, parents=[rec.id], sources=[r["url"] for r in results if r.get("url")])
        s.literature_summary = out.text

    async def hypothesis_stage(self, s: CycleState) -> None:
        async def generate() -> dict:
            h = await propose_hypothesis(self.router, s.question, s.literature,
                                         s.lit_record_id, s.notes())
            view = {"hypothesis": h.hypothesis, "prediction": h.prediction,
                    "rationale": h.rationale}
            if h.warning:
                view["warning"] = h.warning
            return {"h": h, "view": view}

        def modify(p: dict, text: str) -> dict:
            p["h"].hypothesis = text
            p["h"].warning = ""  # the researcher's own wording; the gate showed the warning
            return p

        p = await self._gated("hypothesis", "Hypothesis", generate, s, modify,
                              lambda p: p["h"].record.id)
        h: Hypothesis = p["h"]
        s.hypothesis, s.prediction, s.rationale = h.hypothesis, h.prediction, h.rationale
        s.hypothesis_warning, s.hypothesis_record_id = h.warning, h.record.id

    async def design_stage(self, s: CycleState) -> None:
        h = Hypothesis(s.hypothesis, s.rationale, s.prediction, [],
                       ProvenanceRecord(kind="model", stage="hypothesis", summary="",
                                        id=s.hypothesis_record_id))
        last: dict[str, Critique] = {}

        async def generate() -> dict:
            notes = s.notes()
            if "c" in last and last["c"].level != "ok":
                notes += f"\n- {last['c'].as_note()}"
            d: Design = await design_experiment(self.router, h, notes,
                                                parents=[s.hypothesis_record_id])
            if d.contract is None:  # one automatic retry: no contract, no verdict
                d = await design_experiment(
                    self.router, h, notes + f"\n- The previous draft had no usable "
                    f"pre-registration ({d.contract_error}). Include the full ```json block.",
                    parents=[d.record.id])
            c = await critique(self.router, s.hypothesis, s.prediction, d.contract,
                               d.contract_error, d.code, d.record.id)
            last["c"] = c
            view = {"experiment code": d.code,
                    "preregistration": asdict(d.contract) if d.contract else None,
                    "preregistration_error": d.contract_error, "critic": c.as_view()}
            return {"d": d, "c": c, "view": view}

        def modify(p: dict, text: str) -> dict:
            p["d"].code = text
            p["edited"] = True
            return p

        p = await self._gated("experiment_design", "Experiment (runs only if approved)",
                              generate, s, modify, lambda p: p["c"].record_ids[-1])
        d, c = p["d"], p["c"]
        s.code, s.code_record_id, s.code_hash = d.code, d.record.id, _sha(d.code)
        s.contract = asdict(d.contract) if d.contract else {}
        s.contract_error = d.contract_error
        # The critic is a model, so it informs the researcher rather than capping the verdict;
        # but running a design over its objection is recorded and shown next to the result.
        s.critique = {**c.as_view(), "edited_after": bool(p.get("edited")),
                      "approved_over": c.level if c.level != "ok" else ""}
        if d.contract:
            s.contract_hash = d.contract.fingerprint(s.hypothesis)
            self.log.add(ProvenanceRecord(
                kind="rule", stage="experiment_design",
                summary=f"pre-registration frozen {s.contract_hash}",
                inputs={"hypothesis": s.hypothesis, "contract": s.contract},
                outputs={"contract_hash": s.contract_hash, "code_hash": s.code_hash},
                parents=[d.record.id]))

    async def _run_arms(self, code: str, parent: str) -> dict[str, dict]:
        arms: dict[str, dict] = {}
        for arm in ARMS:
            r = await self.executor.run(code, args=[arm])
            rec = log_execution(self.log, code, r, parents=[parent], args=[arm])
            arms[arm] = {"stdout": r.stdout, "stderr": r.stderr, "exit_code": r.exit_code,
                         "duration_s": r.duration_s, "backend": r.backend,
                         "result": parse_result(r.stdout), "record_id": rec.id}
            if not r.ok:
                break  # a broken script fails every arm; repair before spending more runs
        return arms

    async def execution_stage(self, s: CycleState) -> None:
        parent = s.code_record_id
        for attempt in range(MAX_REPAIRS + 1):  # bounded repair passes
            arms = await self._run_arms(s.code, parent)
            s.arms = arms
            s.backend = next(iter(arms.values()))["backend"]
            s.stdout = "\n".join(f"── {a} ──\n{o['stdout'].rstrip()}" for a, o in arms.items())
            s.stderr = "\n".join(f"── {a} ──\n{o['stderr'].rstrip()}"
                                 for a, o in arms.items() if o["stderr"].strip())
            s.exit_code = next((o["exit_code"] for o in arms.values() if o["exit_code"]), 0)
            s.exec_record_id = list(arms.values())[-1]["record_id"]
            self._save(s)
            problem = arm_problem(arms)
            if problem is None or attempt == MAX_REPAIRS:
                return
            code, repair_rec = await repair_experiment(self.router, s.code, problem,
                                                       s.exec_record_id)
            s.code, s.repaired, parent = code, True, repair_rec.id

    def _verdict(self, s: CycleState) -> Verdict:
        contract = Contract.parse(s.contract) if s.contract else None
        v = decide(contract, s.arms)
        if contract and contract.fingerprint(s.hypothesis) != s.contract_hash:
            v = Verdict("inconclusive",
                        ["The pre-registration changed after you approved it."],
                        v.checks + [Check("Pre-registration intact", False,
                                          "Hash no longer matches the approved one.")])
        return v

    async def analysis_stage(self, s: CycleState) -> None:
        v = self._verdict(s)
        rec = self.log.add(ProvenanceRecord(
            kind="rule", stage="analysis",
            summary=f"verdict {v.verdict}, computed from the pre-registration",
            inputs={"contract": s.contract, "contract_hash": s.contract_hash,
                    "results": {a: o.get("result") for a, o in s.arms.items()}},
            outputs={"verdict": v.verdict, "reasons": v.reasons,
                     "checks": [asdict(c) for c in v.checks]},
            parents=[o["record_id"] for o in s.arms.values()]))
        s.verdict, s.verdict_reasons = v.verdict, v.reasons
        s.checks, s.verdict_record_id = [asdict(c) for c in v.checks], rec.id
        self._save(s)
        a = await analyse(self.router, s.hypothesis, s.prediction, s.contract, s.arms, v, rec.id)
        s.findings, s.caveats, s.analysis_record_id = a.findings, a.caveats, a.record.id

    async def reflection_stage(self, s: CycleState) -> None:
        failed_checks = [f"{c['name']}: {c['detail']}" for c in s.checks if not c["passed"]]
        summary = (f"Question: {s.question}\nQuestion triage: {s.triage.get('category', '')}"
                   f"\nHypothesis: {s.hypothesis}\nPre-registration: {s.contract or 'none'}\n"
                   f"Design critic: {s.critique.get('level', '')}: "
                   f"{s.critique.get('summary', '')}"
                   + (" (the researcher ran it anyway)" if s.critique.get("approved_over")
                      else "") + "\n"
                   f"Code repaired after failure: {s.repaired}\nExit code: {s.exit_code}\n"
                   f"Verdict: {s.verdict}\nVerdict reasons: {s.verdict_reasons or 'none'}\n"
                   f"Failed checks: {failed_checks or 'none'}\nFindings: {s.findings}\n"
                   f"Caveats: {s.caveats}\nResearcher input: {s.human_notes}")

        async def generate() -> dict:
            r = await reflect(self.router, summary, s.lessons_before, s.analysis_record_id,
                              verdict=s.verdict, reasons=s.verdict_reasons)
            return {"r": r, "view": {
                "what worked": r.what_worked, "what failed": r.what_failed,
                "change": r.change_summary,
                "lessons before": "\n".join(f"- {l}" for l in r.lessons_before) or "(none)",
                "lessons after": "\n".join(f"- {l}" for l in r.lessons_after) or "(none)"}}

        def modify(p: dict, text: str) -> dict:
            p["r"].lessons_after = [l.strip() for l in text.split(";") if l.strip()]
            return p

        p = await self._gated("strategy_update", "Strategy update (applies to future cycles)",
                              generate, s, modify, lambda p: p["r"].record.id)
        r = p["r"]
        s.what_worked, s.what_failed, s.change_summary = (
            r.what_worked, r.what_failed, r.change_summary)
        s.lessons_after = r.lessons_after
        self.store.kv_set(LESSONS_KEY, r.lessons_after)

    def notebook_stage(self, s: CycleState) -> Path:
        pid = self.log.project_id
        nb = build_notebook(
            project_id=pid, question=s.question, state=s, records=self.store.records(pid),
            decisions=self.store.decisions(pid), total_cost=self.store.project_cost(pid))
        path = write_notebook(nb, Path(self.notebook_dir) / f"{pid}.ipynb")
        s.notebook_path = str(path)
        self.store.update_project(pid, notebook_path=str(path))
        return path

    # --- driver -------------------------------------------------------------------------

    async def run(self, question: str) -> CycleState:
        s = CycleState(question=question, lessons_before=self.store.kv_get(LESSONS_KEY, []))
        stages = [("triage", self.triage_stage), ("literature", self.literature_stage),
                  ("hypothesis", self.hypothesis_stage),
                  ("experiment_design", self.design_stage), ("execution", self.execution_stage),
                  ("analysis", self.analysis_stage), ("reflection", self.reflection_stage),
                  ("notebook", self._notebook_async)]
        try:
            for name, stage in stages:
                s.stage = name
                self._save(s)
                await stage(s)
            s.stage = "done"
            self._save(s)
        except Exception:
            self.store.update_project(self.log.project_id, status="failed")
            raise
        self.store.update_project(self.log.project_id, status="done")
        return s

    async def _notebook_async(self, s: CycleState) -> None:
        self.notebook_stage(s)
