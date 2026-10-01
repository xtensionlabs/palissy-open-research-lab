"""Question triage: say up front when a question is fiction or can't be tested by simulation."""

from dataclasses import asdict, dataclass

from ..models import ModelRouter
from .common import complete_json

CATEGORIES = {
    "testable": "Testable by a small simulation or computation.",
    "fiction": "Built on fiction or a premise that isn't real biology.",
    "needs_wet_lab": "Needs lab or field data that a simulation can't stand in for.",
    "not_empirical": "Not an empirical question (a matter of definition, ethics or taste).",
}

TRIAGE_SYSTEM = (
    "You triage research questions for a computational biology lab whose experiments are small "
    "numpy simulations. Classify the question as one of: " +
    "; ".join(f"{k} ({v})" for k, v in CATEGORIES.items()) +
    ". If it is not 'testable', you MUST propose the closest real, testable question a "
    "simulation could answer, in one sentence, keeping the researcher's underlying interest "
    "(for a fictional superhuman, the real biology behind the trait). Be direct and plain; no "
    'hedging. Reply with JSON only: {"category": str, "reason": str (one sentence), '
    '"reframe": str (required unless testable)}.'
)


@dataclass
class Triage:
    category: str
    reason: str
    reframe: str
    record_id: str

    @property
    def testable(self) -> bool:
        return self.category == "testable"

    def as_view(self, question: str) -> dict:
        return {**asdict(self), "question": question, "label": CATEGORIES[self.category]}


async def triage(router: ModelRouter, question: str, notes: str = "") -> Triage:
    user = f"Question: {question}"
    if notes:
        user += f"\n\nResearcher context:\n{notes}"
    messages = [{"role": "system", "content": TRIAGE_SYSTEM}, {"role": "user", "content": user}]
    parents: list[str] = []
    for _ in range(2):  # one retry if a non-testable verdict comes back without a reframe
        data, out = await complete_json(router, "triage", messages, max_tokens=1500,
                                        temperature=0.2, parents=parents)
        category = str(data.get("category", "")).strip().lower()
        if category not in CATEGORIES:
            category = "testable"  # unknown label: don't block, the later checks still apply
        reframe = str(data.get("reframe", "")).strip() if category != "testable" else ""
        if category == "testable" or reframe:
            break
        messages = messages + [{"role": "assistant", "content": out.text},
                               {"role": "user", "content": "The reframe is required. Give it."}]
        parents = [out.record.id]
    return Triage(category, str(data.get("reason", "")).strip(), reframe, out.record.id)
