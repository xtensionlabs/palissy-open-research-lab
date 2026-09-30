"""The seven-stage pipeline with human gates.

literature -> hypothesis -> experiment_design -> execution -> analysis -> reflection -> notebook

Gates sit at hypothesis, experiment design (before anything executes), and the strategy update.
Every model/tool call and every human decision lands in the provenance log.
"""

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
from .stages.hypothesis import (Hypothesis, design_experiment, propose_hypothesis,
                                repair_experiment)

MAX_ATTEMPTS = 3
MAX_REPAIRS = 2
LESSONS_KEY = "strategy_lessons"


class PipelineAborted(RuntimeError):
    pass


@dataclass
class CycleState:
    question: str
    stage: str = "literature"
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
    hypothesis_record_id: str = ""
    code: str = ""
    code_record_id: str = ""
    backend: str = ""
    stdout: str = ""
    stderr: str = ""
    exit_code: int = -1
    exec_record_id: str = ""
    repaired: bool = False
    verdict: str = ""
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
            return {"h": h, "view": {"hypothesis": h.hypothesis, "prediction": h.prediction,
                                     "rationale": h.rationale}}

        def modify(p: dict, text: str) -> dict:
            p["h"].hypothesis = text
            return p

        p = await self._gated("hypothesis", "Hypothesis", generate, s, modify,
                              lambda p: p["h"].record.id)
        h: Hypothesis = p["h"]
        s.hypothesis, s.prediction, s.rationale = h.hypothesis, h.prediction, h.rationale
        s.hypothesis_record_id = h.record.id

    async def design_stage(self, s: CycleState) -> None:
        h = Hypothesis(s.hypothesis, s.rationale, s.prediction, [],
                       ProvenanceRecord(kind="model", stage="hypothesis", summary="",
                                        id=s.hypothesis_record_id))

        async def generate() -> dict:
            code, rec = await design_experiment(self.router, h, s.notes(),
                                                parents=[s.hypothesis_record_id])
            return {"code": code, "rec": rec.id, "view": {"experiment code": code}}

        def modify(p: dict, text: str) -> dict:
            p["code"] = text
            return p

        p = await self._gated("experiment_design", "Experiment (runs only if approved)",
                              generate, s, modify, lambda p: p["rec"])
        s.code, s.code_record_id = p["code"], p["rec"]

    async def execution_stage(self, s: CycleState) -> None:
        parent = s.code_record_id
        for attempt in range(MAX_REPAIRS + 1):  # bounded repair passes
            result = await self.executor.run(s.code)
            rec = log_execution(self.log, s.code, result, parents=[parent])
            s.backend, s.stdout, s.stderr = result.backend, result.stdout, result.stderr
            s.exit_code, s.exec_record_id = result.exit_code, rec.id
            if result.ok or attempt == MAX_REPAIRS:
                return
            code, repair_rec = await repair_experiment(
                self.router, s.code, result.stderr or result.stdout, rec.id)
            s.code, s.repaired, parent = code, True, repair_rec.id

    async def analysis_stage(self, s: CycleState) -> None:
        a = await analyse(self.router, s.hypothesis, s.prediction, s.stdout, s.stderr,
                          s.exit_code, s.exec_record_id)
        s.verdict, s.findings, s.caveats = a.verdict, a.findings, a.caveats
        s.analysis_record_id = a.record.id

    async def reflection_stage(self, s: CycleState) -> None:
        summary = (f"Question: {s.question}\nHypothesis: {s.hypothesis}\n"
                   f"Code repaired after failure: {s.repaired}\nExit code: {s.exit_code}\n"
                   f"Verdict: {s.verdict}\nFindings: {s.findings}\nCaveats: {s.caveats}\n"
                   f"Researcher input: {s.human_notes}")

        async def generate() -> dict:
            r = await reflect(self.router, summary, s.lessons_before, s.analysis_record_id)
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
        stages = [("literature", self.literature_stage), ("hypothesis", self.hypothesis_stage),
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
