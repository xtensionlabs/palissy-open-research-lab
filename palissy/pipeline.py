"""The pipeline with human gates.

triage -> literature -> hypothesis -> experiment_design -> execution -> analysis -> reflection
-> notebook

Gates sit at triage (only when the question isn't testable), hypothesis, experiment design
(before anything executes), and the strategy update. Every model/tool call and every human
decision lands in the provenance log. The verdict is computed by rule from the pre-registration,
not by a model.
"""

import hashlib
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

from .db import Store
from .gates import Decision, Gate
from .literature import Literature
from .models import ModelRouter
from .notebook import build_notebook, write_notebook
from .provenance import ProvenanceLog, ProvenanceRecord
from .sandbox import Executor, Job, log_execution, sha
from .stages.analysis import analyse, reflect
from .stages.critic import Critique, critique
from .stages.hypothesis import (Design, Hypothesis, design_experiment, propose_hypothesis,
                                repair_experiment)
from .stages.triage import triage
from .stages.verdict import (ARMS, Check, Contract, Verdict, decide, is_hit,
                             parse_result)

MAX_ATTEMPTS = 3
MAX_REPAIRS = 2
DEFAULT_REPLICATES = 5  # seeds per arm; 3 arms x 5 = 15 branches forked from one checkpoint
DEFAULT_CONCURRENCY = 4  # branches in flight at once (the Beta limit is 50 operations)
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
    replicates: int = 0
    checkpoint: dict = field(default_factory=dict)  # sandbox snapshot every branch forked from
    branches: list = field(default_factory=list)  # one dict per (arm, seed) run, see _branch_row
    tally: dict = field(default_factory=dict)  # arm -> hits / runs / medians, from decide()
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


def branch_row(job: Job, r, record_id: str, key: str = "") -> dict:
    """One sandbox branch as stored in the project state (and shown in the UI)."""
    result = parse_result(r.stdout) if r.ok else None
    if not r.ok:
        status, reason = "rolled_back", ("timed out" if r.exit_code == 124
                                         else f"exit {r.exit_code}")
    elif result is None:
        status, reason = "rolled_back", "no RESULT_JSON line"
    else:
        status, reason = "kept", ""
    return {"id": job.label, "arm": job.arm, "rep": job.rep, "seed_offset": job.seed_offset,
            "exit_code": r.exit_code, "duration_s": r.duration_s, "backend": r.backend,
            "result": result, "stdout": r.stdout, "stderr": r.stderr,
            "stdout_sha": sha(r.stdout), "op_id": r.op_id, "record_id": record_id, "key": key,
            "status": status, "reason": reason}


def branch_problem(branches: list[dict]) -> str | None:
    """What a repair pass should fix, or None if every arm has at least one usable run."""
    for arm in ARMS:
        rows = [b for b in branches if b["arm"] == arm]
        if rows and any(b["status"] == "kept" for b in rows):
            continue
        bad = rows[0] if rows else next((b for b in branches if b["status"] != "kept"), None)
        if bad is None:
            continue
        if bad["exit_code"] != 0:
            return f"[{bad['id']}] exit {bad['exit_code']}\n{bad['stderr'] or bad['stdout']}"
        return (f"[{bad['id']}] finished but printed no valid RESULT_JSON line as its last "
                f"line. Output tail:\n{bad['stdout'][-800:]}")
    return None


def _tally_line(tally: dict) -> str:
    return "; ".join(f"{a} {t['hits']}/{t['ok']} of {t['total']}"
                     for a, t in tally.items()) or "none"


def verdict_input(branches: list[dict]) -> dict[str, list[dict]]:
    arms: dict[str, list[dict]] = {a: [] for a in ARMS}
    for b in branches:
        arms[b["arm"]].append({"exit_code": b["exit_code"], "result": b["result"]})
    return arms


class Pipeline:
    def __init__(self, *, router: ModelRouter, literature: Literature, executor: Executor,
                 gate: Gate, store: Store, log: ProvenanceLog, notebook_dir: str = "notebooks",
                 replicates: int | None = None, concurrency: int | None = None):
        self.router, self.lit, self.executor = router, literature, executor
        self.gate, self.store, self.log = gate, store, log
        self.notebook_dir = notebook_dir
        self.replicates = max(1, replicates or int(
            os.environ.get("PALISSY_REPLICATES", DEFAULT_REPLICATES)))
        self.concurrency = max(1, concurrency or int(
            os.environ.get("PALISSY_MAX_PARALLEL", DEFAULT_CONCURRENCY)))

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

    def _log_branches(self, s: CycleState, code: str, branches, parent: str) -> list[dict]:
        rows = []
        for b in branches:
            rec = log_execution(
                self.log, code, b.result, parents=[parent], args=[b.job.arm],
                meta={"rep": b.job.rep, "seed_offset": b.job.seed_offset, "branch": b.key,
                      "checkpoint": s.checkpoint.get("image", "")})
            rows.append(branch_row(b.job, b.result, rec.id, b.key))
        return rows

    async def execution_stage(self, s: CycleState) -> None:
        """Fork every (arm, seed) run from one checkpoint and run them in parallel.

        A first run goes alone, so a broken script fails once rather than fifteen times and is
        repaired before the fan-out. Branches are disposable: one that fails is rolled back
        (dropped, nothing to undo) and the verdict is read from the survivors.
        """
        parent = s.code_record_id
        s.replicates = self.replicates
        jobs = [Job(a, r) for r in range(self.replicates) for a in ARMS]
        for attempt in range(MAX_REPAIRS + 1):  # bounded repair passes
            started = time.perf_counter()
            ckpt = await self.executor.checkpoint(s.code)
            s.checkpoint = {"backend": ckpt.backend, "image": ckpt.image, "base": ckpt.base,
                            "code_hash": ckpt.code_hash}
            ck_rec = self.log.add(ProvenanceRecord(
                kind="sandbox", stage="checkpoint",
                summary=f"[{ckpt.backend}] checkpoint {ckpt.image[:8] or 'none'}",
                inputs={"code_hash": ckpt.code_hash, "base": ckpt.base},
                outputs={"image": ckpt.image, "base": ckpt.base, "backend": ckpt.backend},
                latency_s=time.perf_counter() - started, parents=[parent]))
            rows = self._log_branches(
                s, s.code, await self.executor.run_branches(ckpt, jobs[:1], concurrency=1),
                ck_rec.id)
            self._record_runs(s, rows)
            if rows[0]["status"] == "kept" and len(jobs) > 1:
                rows += self._log_branches(
                    s, s.code, await self.executor.run_branches(
                        ckpt, jobs[1:], concurrency=self.concurrency), ck_rec.id)
                self._record_runs(s, rows)
            problem = branch_problem(rows)
            if problem is None or attempt == MAX_REPAIRS:
                return
            code, repair_rec = await repair_experiment(self.router, s.code, problem,
                                                       s.exec_record_id)
            s.code, s.repaired, parent = code, True, repair_rec.id

    def _record_runs(self, s: CycleState, rows: list[dict]) -> None:
        s.branches = rows
        s.backend = rows[0]["backend"]
        first = {b["arm"]: b for b in rows if b["rep"] == 0}
        s.stdout = "\n".join(f"── {a} ──\n{b['stdout'].rstrip()}" for a, b in first.items())
        s.stderr = "\n".join(f"── {b['id']} ──\n{b['stderr'].rstrip()}"
                             for b in rows if b["stderr"].strip())
        s.exit_code = next((b["exit_code"] for b in rows if b["exit_code"]), 0)
        s.exec_record_id = rows[-1]["record_id"]
        self._save(s)

    def _verdict(self, s: CycleState) -> Verdict:
        contract = Contract.parse(s.contract) if s.contract else None
        v = decide(contract, verdict_input(s.branches))
        if contract and contract.fingerprint(s.hypothesis) != s.contract_hash:
            v = Verdict("inconclusive",
                        ["The pre-registration changed after you approved it."],
                        v.checks + [Check("Pre-registration intact", False,
                                          "Hash no longer matches the approved one.")], v.tally)
        return v

    async def analysis_stage(self, s: CycleState) -> None:
        v = self._verdict(s)
        rec = self.log.add(ProvenanceRecord(
            kind="rule", stage="analysis",
            summary=f"verdict {v.verdict}, computed from the pre-registration",
            inputs={"contract": s.contract, "contract_hash": s.contract_hash,
                    "results": {b["id"]: b["result"] for b in s.branches}},
            outputs={"verdict": v.verdict, "reasons": v.reasons, "tally": v.tally,
                     "checks": [asdict(c) for c in v.checks]},
            parents=[b["record_id"] for b in s.branches]))
        contract = Contract.parse(s.contract) if s.contract else None
        for b in s.branches:  # mark each run with the same rule the tally used
            b["hit"] = bool(contract and b["status"] == "kept"
                            and is_hit(b["arm"], b["result"], contract))
        s.verdict, s.verdict_reasons, s.tally = v.verdict, v.reasons, v.tally
        s.checks, s.verdict_record_id = [asdict(c) for c in v.checks], rec.id
        self._save(s)
        a = await analyse(self.router, s.hypothesis, s.prediction, s.contract, v, rec.id)
        s.findings, s.caveats, s.analysis_record_id = a.findings, a.caveats, a.record.id

    # --- replay -------------------------------------------------------------------------

    async def replay(self, state: dict) -> dict:
        """Re-run every recorded branch from the clean base image and compare the output.

        Each branch gets the stored script and the same seed offset, in a fresh sandbox that
        shares nothing with the original run, so a match shows the result doesn't depend on
        leftover state. Costs no model tokens.
        """
        branches = state.get("branches") or []
        if not branches or not state.get("code"):
            raise ValueError("this project has no recorded runs to replay")
        started = time.perf_counter()
        ckpt = await self.executor.clean_checkpoint(state["code"])
        jobs = [Job(b["arm"], b["rep"]) for b in branches]
        try:
            again = await self.executor.run_branches(
                ckpt, jobs, concurrency=self.concurrency, clean=True)
        finally:
            await self._close_executor()
        items = []
        for b, a in zip(branches, again):
            same_out = sha(a.result.stdout) == b["stdout_sha"]
            same_exit = a.result.exit_code == b["exit_code"]
            items.append({"id": b["id"], "match": same_out and same_exit,
                          "expected": b["stdout_sha"], "actual": sha(a.result.stdout),
                          "exit_code": a.result.exit_code, "op_id": a.result.op_id})
        out = {"ts": time.time(), "backend": again[0].result.backend if again else "",
               "base": ckpt.base, "code_hash": ckpt.code_hash, "total": len(items),
               "matched": sum(i["match"] for i in items), "items": items,
               "duration_s": round(time.perf_counter() - started, 1),
               "original_backend": state.get("backend", "")}
        self.log.add(ProvenanceRecord(
            kind="rule", stage="replay",
            summary=f"replayed {out['total']} runs in clean sandboxes: {out['matched']} matched",
            inputs={"code_hash": ckpt.code_hash, "base": ckpt.base},
            outputs={k: out[k] for k in ("total", "matched", "items", "backend")},
            latency_s=out["duration_s"], parents=[b["record_id"] for b in branches]))
        self.store.kv_set(f"replay:{self.log.project_id}", out)
        return out

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
                   f"Runs by arm (hits / readable runs of total): {_tally_line(s.tally)}\n"
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
        finally:
            await self._close_executor()
        self.store.update_project(self.log.project_id, status="done")
        return s

    async def _close_executor(self) -> None:
        close = getattr(self.executor, "close", None)
        if close:
            try:
                await close()
            except Exception:  # cleanup must never turn a finished run into a failed one
                pass

    async def _notebook_async(self, s: CycleState) -> None:
        self.notebook_stage(s)
