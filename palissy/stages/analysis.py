"""Analysis (Super) and reflection (Ultra). Reflection produces an explicit strategy diff.

The verdict is computed mechanically in `verdict.py` before analysis runs. The analyst writes
findings and caveats for that verdict; it cannot change it.
"""

import json
from dataclasses import dataclass, field

from ..models import ModelRouter
from ..provenance import ProvenanceRecord
from .common import complete_json
from .verdict import Verdict

ANALYSIS_SYSTEM = (
    "You write up the result of a computational experiment for a biology researcher. The "
    "verdict has already been computed mechanically from a pre-registered test and its "
    "positive and negative controls; do not argue with it or restate it more strongly. "
    "Explain in plain words what the numbers show and, if the verdict is inconclusive or "
    "failed, why the run can't answer the question. A simulation speaks only within its own "
    'assumptions. Reply with JSON only: {"findings": str (2-3 sentences), "caveats": [str]}.'
)

REFLECTION_SYSTEM = (
    "You are the reflection step of a research loop. Given one full cycle (question, hypothesis, "
    "experiment, outcome, analysis) and the current list of strategy lessons, decide what should "
    "change in how FUTURE cycles are run. Lessons must be short, concrete, actionable "
    "instructions to the hypothesis and experiment-design steps (e.g. about scope, runtime, "
    "modelling choices, what evidence to require). Keep useful existing lessons, drop obsolete "
    "ones, add new ones; at most 8 lessons. Every experiment arm must run in under 20 seconds on "
    "one CPU core with numpy only, so never recommend long runs, huge genomes or heavy compute. "
    "If the verdict is inconclusive or failed, the result is unusable: what_worked may only "
    "describe the process (never the result, the test or the conclusion), and what_failed must "
    "name every flaw listed under 'Verdict reasons'. "
    'Reply with JSON only: {"what_worked": str, "what_failed": str, '
    '"lessons": [str], "change_summary": str}.'
)


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


async def analyse(router: ModelRouter, hypothesis: str, prediction: str, contract: dict,
                  arms: dict[str, dict], verdict: Verdict, parent_id: str) -> Analysis:
    arm_text = "\n".join(
        f"[{a}] exit={o.get('exit_code')} result={json.dumps(o.get('result'))}\n"
        f"{(o.get('stdout') or '')[-1200:]}{(o.get('stderr') or '')[-400:]}"
        for a, o in arms.items())
    checks = "\n".join(f"- {c.name}: {'pass' if c.passed else 'FAIL'} ({c.detail})"
                       for c in verdict.checks)
    user = (f"Hypothesis: {hypothesis}\nPrediction: {prediction}\n"
            f"Pre-registration: {json.dumps(contract)}\n\nVerdict: {verdict.verdict}\n"
            f"Checks:\n{checks}\nVerdict reasons: {verdict.reasons or 'none'}\n\n"
            f"Arms:\n{arm_text}")
    data, out = await complete_json(
        router, "analysis",
        [{"role": "system", "content": ANALYSIS_SYSTEM}, {"role": "user", "content": user}],
        max_tokens=3000, parents=[parent_id],
    )
    caveats = [str(c) for c in data.get("caveats", []) if str(c).strip()]
    return Analysis(verdict.verdict, str(data.get("findings", "")), caveats, out.record)


def unusable_prefix(verdict: str, reasons: list[str]) -> str:
    """What reflection must record first when the run can't be reported as a result."""
    if verdict not in ("inconclusive", "failed") or not reasons:
        return ""
    return "Result unusable: " + " ".join(reasons)


async def reflect(router: ModelRouter, cycle_summary: str, lessons: list[str],
                  parent_id: str, verdict: str = "", reasons: list[str] | None = None
                  ) -> Reflection:
    user = (f"Current lessons:\n" + ("\n".join(f"- {l}" for l in lessons) or "(none)")
            + f"\n\nCycle:\n{cycle_summary}")
    data, out = await complete_json(
        router, "reflection",
        [{"role": "system", "content": REFLECTION_SYSTEM}, {"role": "user", "content": user}],
        max_tokens=8000, parents=[parent_id],  # Ultra thinks first; 4000 ran out mid-answer
    )
    after = [str(l).strip() for l in data.get("lessons", []) if str(l).strip()][:8]
    what_failed = str(data.get("what_failed", ""))
    # Enforced in code, not just asked for: the guard's reasons always lead "what failed".
    prefix = unusable_prefix(verdict, reasons or [])
    if prefix:
        what_failed = f"{prefix} {what_failed}".strip()
    return Reflection(
        what_worked=str(data.get("what_worked", "")), what_failed=what_failed,
        lessons_before=list(lessons), lessons_after=after,
        change_summary=str(data.get("change_summary", "")), record=out.record,
    )
