"""Hypothesis + experiment design + repair. Ultra proposes; Super writes and fixes the code.

The design step returns two things: a pre-registration contract (see `verdict.py`) and a script
that runs one arm per invocation (treatment, positive control, negative control).
"""

import json
import re
from dataclasses import dataclass

from ..models import ModelRouter
from ..provenance import ProvenanceRecord
from .common import complete_json, extract_code, extract_json
from .verdict import Contract

HYPOTHESIS_SYSTEM = (
    "You are a computational biology research collaborator. Propose ONE falsifiable hypothesis "
    "that can be tested with a small self-contained Python computation (no network, no "
    "external data files, standard library plus numpy only). Ground it in the provided "
    "literature excerpts and cite them by [n]. The hypothesis must make a claim the result "
    "could contradict: a direction or size of effect (for example 'higher X increases Y' or "
    "'A changes B by more than C'). Never frame it as an impossibility or an absence "
    "('cannot', 'never', 'impossible', 'no evidence'): a run that finds nothing would then "
    "'support' it by default. Be brief: the hypothesis is ONE sentence of at most "
    "30 words, the prediction one sentence of at most 25 words, the rationale at most 40 words. "
    "Reply with JSON only: "
    '{"hypothesis": str, "rationale": str, "prediction": str, "cited": [int]}.'
)

# Framings where finding nothing counts as success, so the test can't come out the other way.
UNFALSIFIABLE = re.compile(
    r"\b(cannot|can ?not|can't|could not|couldn't|never|impossible|not possible|unable to|"
    r"no evidence)\b", re.I)

ARM_PROTOCOL = (
    "The script runs ONE arm per invocation. Read it with: arm = next((a for a in sys.argv[1:] "
    "if a in ('treatment', 'positive', 'negative')), 'treatment'). Every arm compares a "
    "baseline group with a comparison group using the SAME test, seed, sizes and statistic:\n"
    "- treatment: comparison group = the condition the hypothesis is about.\n"
    "- positive: comparison group = baseline with an effect of known, clearly detectable size "
    "planted on purpose, in the predicted direction. The test must detect it.\n"
    "- negative: comparison group = a second independent draw from the baseline (no effect by "
    "construction). The test must not detect it.\n"
    "Tests: a permutation test computes the statistic on the real group labels, then shuffles "
    "the labels between the two groups (e.g. 1000 times) and recomputes it; p = (1 + number of "
    "shuffled statistics at least as extreme) / (1 + shuffles). It needs two groups of samples. "
    "A binomial test against an invented probability is not a permutation test, and the null "
    "must come from the model itself (the baseline), never from a guessed number. Choose "
    "parameters so the outcome is not decided before running: rates x steps must give counts "
    "comparable to any threshold, not orders of magnitude away.\n"
    "The last line printed must be: RESULT_JSON: {\"arm\": arm, \"effect\": <float, signed, "
    "comparison minus baseline>, \"p_value\": <float>, \"n\": <int samples per group>, "
    "\"successes\": <int count of events in the comparison group, or null>}. Use json.dumps."
)

CODE_SYSTEM = (
    "You design and pre-register a computational experiment that tests the hypothesis by "
    "simulation or analysis. Reply with TWO fenced blocks, in this order.\n"
    "1. A ```json block, the pre-registration, committed before anything runs: "
    '{"statistic": what is measured, "test": the statistical test and how it is computed, '
    '"null": the null model, "alpha": significance threshold (normally 0.05), '
    '"direction": "increase" | "decrease" | "any" (predicted sign of effect), '
    '"min_effect": the smallest |effect| that counts as support, on the same scale the script '
    "reports as effect (0 if the hypothesis names no size; if it says e.g. 'more than 8-fold', "
    "report effect as the fold change minus 1, or similar, and set min_effect to match), "
    '"supports_if": the result that would support the hypothesis, '
    '"refutes_if": the result that would refute it, '
    '"positive_control": the effect planted in the positive arm and its size, '
    '"negative_control": how the negative arm guarantees no effect}.\n'
    "2. A ```python block: a single self-contained Python 3 script. Standard library and numpy "
    "only (scipy is NOT installed and numpy has no erf; use math.erf), no network, no file "
    "I/O, deterministic (fixed seed). HARD LIMIT: each arm must finish in under 20 seconds on "
    "one CPU core, so use small populations, few loci and a fixed, modest number of steps; "
    "never loop until convergence. Keep it short and readable: at most 60 lines, no helper "
    "classes, minimal comments.\n" + ARM_PROTOCOL
)

REPAIR_SYSTEM = (
    "The experiment script below failed, timed out, or did not print its RESULT_JSON line. "
    "Read the error, identify the exact failing line, and do NOT repeat the same call or "
    "approach. Keep the scientific intent, the three arms and the test, but cut the computation "
    "(fewer steps, smaller sizes, vectorise) so each arm finishes in under 20 seconds. Same "
    "rules as before: standard library and numpy only, deterministic.\n" + ARM_PROTOCOL +
    "\nReply with only the corrected code in one ```python block."
)


@dataclass
class Hypothesis:
    hypothesis: str
    rationale: str
    prediction: str
    cited: list[int]
    record: ProvenanceRecord
    warning: str = ""  # set when the phrasing is still unfalsifiable after one retry


@dataclass
class Design:
    code: str
    contract: Contract | None
    contract_raw: dict
    contract_error: str
    record: ProvenanceRecord


def format_literature(results: list[dict], limit: int = 1200) -> str:
    return "\n\n".join(
        f"[{i}] {r.get('title')} ({r.get('url')})\n{(r.get('content') or '')[:limit]}"
        for i, r in enumerate(results, 1)
    )


def phrasing_problem(h: str, prediction: str = "") -> str:
    """Why this hypothesis can't come out the other way, or '' if it can."""
    m = UNFALSIFIABLE.search(f"{h} {prediction}")
    if not m:
        return ""
    return (f"It is framed as an absence (“{m.group(0)}”), so a run that finds "
            "nothing would count as support.")


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
    messages = [{"role": "system", "content": HYPOTHESIS_SYSTEM},
                {"role": "user", "content": user}]
    sources = [r["url"] for r in literature if r.get("url")]
    parents = [lit_record_id]
    for attempt in range(2):  # one automatic retry if the phrasing is unfalsifiable
        data, out = await complete_json(router, "hypothesis", messages, max_tokens=6000,
                                        sources=sources, parents=parents)
        h = Hypothesis(
            hypothesis=data["hypothesis"], rationale=data.get("rationale", ""),
            prediction=data.get("prediction", ""), cited=data.get("cited", []),
            record=out.record,
        )
        problem = phrasing_problem(h.hypothesis, h.prediction)
        if not problem:
            return h
        messages = messages + [
            {"role": "assistant", "content": out.text},
            {"role": "user", "content": f"Rewrite it. {problem} State a direction or size of "
                                        "effect that the result could contradict."}]
        parents = [out.record.id]
    h.warning = problem
    return h


def _json_block(text: str) -> dict:
    m = re.search(r"```json\s*\n(.*?)```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    return extract_json(text.split("```python")[0])


async def design_experiment(
    router: ModelRouter, h: Hypothesis, notes: str = "", parents: list[str] | None = None
) -> Design:
    user = f"Hypothesis: {h.hypothesis}\nPrediction: {h.prediction}"
    if notes:
        user += f"\n\nGuidance (strategy lessons, researcher input, critic notes):\n{notes}"
    out = await router.complete(
        "experiment_design",
        [{"role": "system", "content": CODE_SYSTEM}, {"role": "user", "content": user}],
        max_tokens=5000,
        parents=parents or [h.record.id],
    )
    raw: dict = {}
    contract, error = None, ""
    try:
        raw = _json_block(out.text)
        contract = Contract.parse(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        error = str(exc) if raw else "no pre-registration block in the design"
    return Design(extract_code(out.text), contract, raw, error, out.record)


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
