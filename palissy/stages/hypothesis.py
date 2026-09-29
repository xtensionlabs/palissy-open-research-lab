"""Hypothesis + experiment design. Ultra proposes; Super writes the experiment code."""

import json
import re
from dataclasses import dataclass

from ..models import ModelRouter
from ..provenance import ProvenanceRecord

HYPOTHESIS_SYSTEM = (
    "You are a computational biology research collaborator. Propose ONE falsifiable hypothesis "
    "that can be tested with a small self-contained Python computation (no network, no "
    "external data files, standard library plus numpy only). Ground it in the provided "
    "literature excerpts and cite them by [n]. Reply with JSON only: "
    '{"hypothesis": str, "rationale": str, "prediction": str, "cited": [int]}.'
)

CODE_SYSTEM = (
    "Write a single self-contained Python 3 script that tests the hypothesis by simulation or "
    "analysis. Standard library and numpy only, no network, deterministic (fixed seed), under "
    "30 seconds. Print clear results and end with a line 'RESULT: supports' or "
    "'RESULT: refutes' or 'RESULT: inconclusive'. Reply with only the code in one "
    "```python block."
)


@dataclass
class Hypothesis:
    hypothesis: str
    rationale: str
    prediction: str
    cited: list[int]
    record: ProvenanceRecord


def _extract_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object in model output: {text[:200]!r}")
    return json.loads(match.group(0))


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
    strategy_notes: str = "",
) -> Hypothesis:
    user = f"Research question: {question}\n\nLiterature:\n{format_literature(literature)}"
    if strategy_notes:
        user += f"\n\nStrategy notes from earlier cycles:\n{strategy_notes}"
    out = await router.complete(
        "hypothesis",
        [{"role": "system", "content": HYPOTHESIS_SYSTEM}, {"role": "user", "content": user}],
        max_tokens=4000,
        sources=[r["url"] for r in literature if r.get("url")],
        parents=[lit_record_id],
    )
    data = _extract_json(out.text)
    return Hypothesis(
        hypothesis=data["hypothesis"], rationale=data.get("rationale", ""),
        prediction=data.get("prediction", ""), cited=data.get("cited", []),
        record=out.record,
    )


async def design_experiment(router: ModelRouter, h: Hypothesis) -> tuple[str, ProvenanceRecord]:
    user = f"Hypothesis: {h.hypothesis}\nPrediction: {h.prediction}"
    out = await router.complete(
        "experiment_design",
        [{"role": "system", "content": CODE_SYSTEM}, {"role": "user", "content": user}],
        max_tokens=4000,
        parents=[h.record.id],
    )
    match = re.search(r"```(?:python)?\n(.*?)```", out.text, re.DOTALL)
    return (match.group(1) if match else out.text).strip(), out.record
