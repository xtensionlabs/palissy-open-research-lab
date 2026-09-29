"""Analysis (Super) and reflection (Ultra). Reflection produces an explicit strategy diff."""

import re
from dataclasses import dataclass, field

from ..models import ModelRouter
from ..provenance import ProvenanceRecord
from .common import extract_json

VERDICTS = ("supports", "refutes", "inconclusive", "failed")

ANALYSIS_SYSTEM = (
    "You analyse the result of a computational experiment for a biology researcher. Be "
    "conservative: a simulation supports a hypothesis only within the model's assumptions. "
    'Reply with JSON only: {"verdict": "supports|refutes|inconclusive|failed", '
    '"findings": str, "caveats": [str]}.'
)

REFLECTION_SYSTEM = (
    "You are the reflection step of a research loop. Given one full cycle (question, hypothesis, "
    "experiment, outcome, analysis) and the current list of strategy lessons, decide what should "
    "change in how FUTURE cycles are run. Lessons must be short, concrete, actionable "
    "instructions to the hypothesis and experiment-design steps (e.g. about scope, runtime, "
    "modelling choices, what evidence to require). Keep useful existing lessons, drop obsolete "
    "ones, add new ones; at most 8 lessons. Every experiment must run in under 20 seconds on one "
    "CPU core with numpy only, so never recommend long runs, huge genomes or heavy compute. "
    'Reply with JSON only: {"what_worked": str, "what_failed": str, '
    '"lessons": [str], "change_summary": str}.'
)


def script_result(stdout: str) -> str | None:
    """The experiment's own final 'RESULT: <x>' line, if any."""
    matches = re.findall(r"^RESULT:\s*(supports|refutes|inconclusive)", stdout, re.M | re.I)
    return matches[-1].lower() if matches else None


@dataclass
class Analysis:
    verdict: str
    findings: str
    caveats: list[str]
    record: ProvenanceRecord


@dataclass
class Reflection:
    what_worked: str
    what_failed: str
    lessons_before: list[str]
    lessons_after: list[str]
    change_summary: str
    record: ProvenanceRecord
    extra: dict = field(default_factory=dict)


async def analyse(router: ModelRouter, hypothesis: str, prediction: str, stdout: str,
                  stderr: str, exit_code: int, parent_id: str) -> Analysis:
    user = (f"Hypothesis: {hypothesis}\nPrediction: {prediction}\nExit code: {exit_code}\n"
            f"stdout:\n{stdout[-3000:]}\nstderr:\n{stderr[-1000:]}")
    out = await router.complete(
        "analysis",
        [{"role": "system", "content": ANALYSIS_SYSTEM}, {"role": "user", "content": user}],
        max_tokens=3000, parents=[parent_id],
    )
    data = extract_json(out.text)
    verdict = data.get("verdict", "inconclusive")
    if exit_code != 0:
        verdict = "failed"  # never let the model overrule a non-zero exit
    elif verdict not in VERDICTS:
        verdict = "inconclusive"
    elif script_result(stdout) == "inconclusive":
        verdict = "inconclusive"  # the experiment itself said so; analysis may not overstate it
    return Analysis(verdict, data.get("findings", ""), data.get("caveats", []), out.record)


async def reflect(router: ModelRouter, cycle_summary: str, lessons: list[str],
                  parent_id: str) -> Reflection:
    user = (f"Current lessons:\n" + ("\n".join(f"- {l}" for l in lessons) or "(none)")
            + f"\n\nCycle:\n{cycle_summary}")
    out = await router.complete(
        "reflection",
        [{"role": "system", "content": REFLECTION_SYSTEM}, {"role": "user", "content": user}],
        max_tokens=4000, parents=[parent_id],
    )
    data = extract_json(out.text)
    after = [str(l).strip() for l in data.get("lessons", []) if str(l).strip()][:8]
    return Reflection(
        what_worked=data.get("what_worked", ""), what_failed=data.get("what_failed", ""),
        lessons_before=list(lessons), lessons_after=after,
        change_summary=data.get("change_summary", ""), record=out.record,
    )
