"""Hypothesis + experiment design + repair. Ultra proposes; Super writes and fixes the code."""

from dataclasses import dataclass

from ..models import ModelRouter
from ..provenance import ProvenanceRecord
from .common import extract_code, extract_json

HYPOTHESIS_SYSTEM = (
    "You are a computational biology research collaborator. Propose ONE falsifiable hypothesis "
    "that can be tested with a small self-contained Python computation (no network, no "
    "external data files, standard library plus numpy only). Ground it in the provided "
    "literature excerpts and cite them by [n]. Reply with JSON only: "
    '{"hypothesis": str, "rationale": str, "prediction": str, "cited": [int]}.'
)

CODE_SYSTEM = (
    "Write a single self-contained Python 3 script that tests the hypothesis by simulation or "
    "analysis. Standard library and numpy only, no network, no file I/O, deterministic (fixed "
    "seed). HARD LIMIT: it must finish in under 20 seconds on one CPU core, so use small "
    "populations, few loci and a fixed, modest number of steps; never loop until convergence. "
    "Print clear results and end with a line 'RESULT: supports' or 'RESULT: refutes' or "
    "'RESULT: inconclusive'. Reply with only the code in one ```python block."
)

REPAIR_SYSTEM = (
    "The experiment script below failed or timed out. Fix it. Keep the scientific intent, but "
    "cut the computation (fewer steps, smaller sizes, vectorise) so it finishes in under 20 "
    "seconds. Same rules as before: standard library and numpy only, deterministic, ends with a "
    "'RESULT: ...' line. Reply with only the corrected code in one ```python block."
)


@dataclass
class Hypothesis:
    hypothesis: str
    rationale: str
    prediction: str
    cited: list[int]
    record: ProvenanceRecord


def format_literature(results: list[dict], limit: int = 1200) -> str:
    return "\n\n".join(
        f"[{i}] {r.get('title')} ({r.get('url')})\n{(r.get('content') or '')[:limit]}"
        for i, r in enumerate(results, 1)
    )


async def propose_hypothesis(
    router: ModelRouter,
    question: str,
    literature: list[dict],
    lit_record_id: str,
    notes: str = "",
) -> Hypothesis:
    user = f"Research question: {question}\n\nLiterature:\n{format_literature(literature)}"
    if notes:
        user += f"\n\nGuidance (strategy lessons and researcher input):\n{notes}"
    out = await router.complete(
        "hypothesis",
        [{"role": "system", "content": HYPOTHESIS_SYSTEM}, {"role": "user", "content": user}],
        max_tokens=4000,
        sources=[r["url"] for r in literature if r.get("url")],
        parents=[lit_record_id],
    )
    data = extract_json(out.text)
    return Hypothesis(
        hypothesis=data["hypothesis"], rationale=data.get("rationale", ""),
        prediction=data.get("prediction", ""), cited=data.get("cited", []),
        record=out.record,
    )


async def design_experiment(
    router: ModelRouter, h: Hypothesis, notes: str = "", parents: list[str] | None = None
) -> tuple[str, ProvenanceRecord]:
    user = f"Hypothesis: {h.hypothesis}\nPrediction: {h.prediction}"
    if notes:
        user += f"\n\nGuidance (strategy lessons and researcher input):\n{notes}"
    out = await router.complete(
        "experiment_design",
        [{"role": "system", "content": CODE_SYSTEM}, {"role": "user", "content": user}],
        max_tokens=4000,
        parents=parents or [h.record.id],
    )
    return extract_code(out.text), out.record


async def repair_experiment(
    router: ModelRouter, code: str, error: str, parent_id: str
) -> tuple[str, ProvenanceRecord]:
    user = f"Script:\n```python\n{code}\n```\n\nFailure:\n{error[-1500:]}"
    out = await router.complete(
        "code_generation",
        [{"role": "system", "content": REPAIR_SYSTEM}, {"role": "user", "content": user}],
        max_tokens=4000,
        parents=[parent_id],
    )
    return extract_code(out.text), out.record
