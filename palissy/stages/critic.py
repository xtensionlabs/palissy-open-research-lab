"""Design critic: reads the pre-registration and code before the researcher's gate.

Super checks every design. Only if it raises a concern does Ultra take a second look, so the
expensive model is spent where a critic says it is needed (cost that steers, not just reports).
"""

import json
from dataclasses import asdict, dataclass, field

from ..models import Flavor, ModelRouter
from .common import complete_json, extract_json
from .verdict import Contract

LEVELS = ("ok", "concern", "blocking")

QUESTIONS = {
    "knowable_in_advance": "Could the outcome be known without running it? Do a quick "
                           "back-of-envelope with the script's own parameters (rates x steps, "
                           "expected counts vs any threshold).",
    "null_is_real": "Is the null a real null, derived from the baseline model, rather than an "
                    "invented probability or a number chosen by hand?",
    "test_matches_claim": "Does the test do what the pre-registration says (e.g. a "
                          "'permutation test' really shuffles labels between two groups), and "
                          "do the positive and negative arms really plant and exclude an "
                          "effect? If the hypothesis names a size, does min_effect encode it "
                          "on the same scale as the script's effect?",
}

CRITIC_SYSTEM = (
    "You are a sceptical reviewer checking a computational experiment BEFORE it runs. Your job "
    "is to catch designs whose result is decided in advance or whose test cannot come out the "
    "other way. Answer each question in one or two plain sentences, citing numbers from the "
    "code. Mark a question false only for a real flaw, not a style point. A fixed random seed "
    "is required for reproducibility and is never a flaw. A large, obvious effect in the "
    "POSITIVE arm is intended; ask instead whether the TREATMENT arm's outcome is implied by "
    "parameters the design itself chose (e.g. an effect size picked to clear the threshold). "
    "Overall level: ok (no flaw), concern (a flaw that weakens the result), blocking (the "
    "result is meaningless as designed). Reply with JSON only: "
    '{"level": "ok|concern|blocking", "answers": {' +
    ", ".join(f'"{k}": {{"ok": bool, "why": str}}' for k in QUESTIONS) +
    '}, "summary": str (one sentence)}.\nQuestions:\n' +
    "\n".join(f"- {k}: {q}" for k, q in QUESTIONS.items())
)


@dataclass
class Critique:
    level: str
    answers: dict[str, dict]  # question key -> {"ok": bool, "why": str}
    summary: str
    checked_by: list[str] = field(default_factory=list)  # flavors, in order
    record_ids: list[str] = field(default_factory=list)

    def as_view(self) -> dict:
        return asdict(self)

    def as_note(self) -> str:
        flaws = [f"{k}: {a['why']}" for k, a in self.answers.items() if not a.get("ok", True)]
        return f"Design critic ({self.level}) on the previous draft: " + (
            "; ".join(flaws) or self.summary)


def _parse(reply: str | dict) -> tuple[str, dict[str, dict], str]:
    data = extract_json(reply) if isinstance(reply, str) else reply
    answers = {}
    for k in QUESTIONS:
        a = (data.get("answers") or {}).get(k) or {}
        answers[k] = {"ok": bool(a.get("ok", False)), "why": str(a.get("why", "")).strip()
                      or "No answer given."}
    level = str(data.get("level", "")).lower()
    if level not in LEVELS:
        level = "concern"
    if level == "ok" and not all(a["ok"] for a in answers.values()):
        level = "concern"  # an "ok" with a failed question is not ok
    return level, answers, str(data.get("summary", "")).strip()


async def critique(router: ModelRouter, hypothesis: str, prediction: str,
                   contract: Contract | None, contract_error: str, code: str,
                   parent_id: str) -> Critique:
    prereg = (json.dumps(asdict(contract), indent=1) if contract
              else f"(missing or incomplete: {contract_error})")
    user = (f"Hypothesis: {hypothesis}\nPrediction: {prediction}\n\nPre-registration:\n{prereg}"
            f"\n\nScript:\n```python\n{code}\n```")
    messages = [{"role": "system", "content": CRITIC_SYSTEM}, {"role": "user", "content": user}]

    data, out = await complete_json(router, "design_critic", messages, max_tokens=4000,
                                    temperature=0.2, parents=[parent_id])
    level, answers, summary = _parse(data)
    c = Critique(level, answers, summary, [Flavor.SUPER.value], [out.record.id])
    if level == "ok":
        return c
    # Escalate: a second, deeper read decides whether the concern stands.
    out2 = await router.complete("design_critic_escalated", messages, max_tokens=8000,
                                 temperature=0.2, parents=[out.record.id])
    try:
        level2, answers2, summary2 = _parse(out2.text)
    except (ValueError, json.JSONDecodeError):
        # Ultra ran out of room before answering; keep the first critic's objection standing.
        c.checked_by.append("ultra (no answer)")
        c.record_ids.append(out2.record.id)
        return c
    return Critique(level2, answers2, summary2, [Flavor.SUPER.value, Flavor.ULTRA.value],
                    [out.record.id, out2.record.id])
