"""Single home for model resolution, routing policy, and call logging (CLAUDE.md §2.2, §4).

Every model call in Palissy goes through `ModelRouter.complete`, which logs model, tokens,
cost and latency as a provenance record.
"""

import json
import re
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from openai import AsyncOpenAI

from .config import TOKEN_FACTORY_BASE_URL, Settings
from .provenance import ProvenanceLog, ProvenanceRecord


class Flavor(str, Enum):
    NANO = "nano"
    SUPER = "super"
    ULTRA = "ultra"


# Routing policy: one place, not scattered ifs.
STAGE_POLICY: dict[str, Flavor] = {
    "literature_summary": Flavor.NANO,
    "hypothesis": Flavor.ULTRA,
    "experiment_design": Flavor.SUPER,
    "code_generation": Flavor.SUPER,
    "analysis": Flavor.SUPER,
    "reflection": Flavor.ULTRA,
    "notebook": Flavor.NANO,
}

# Why each stage gets the model it does, in plain words (shown in the UI's cost view).
ROUTING_REASONS: dict[str, str] = {
    "literature_summary": "Summarising sources is light work, so the smallest model is enough.",
    "hypothesis": "Proposing a testable idea is the hardest step, so it gets the deepest model.",
    "experiment_design": "Writing runnable code needs a dependable coder, not the priciest thinker.",
    "code_generation": "Fixing a failed script is code work, so it stays on the code model.",
    "analysis": "Reading a result against its hypothesis needs care but not heavy reasoning.",
    "reflection": "Reflection rewrites the strategy for every future run, so depth pays off.",
    "notebook": "Assembling the record is mechanical, so the smallest model is enough.",
}

# USD per 1M tokens (input, output), copied from the Token Factory console. The /v1/models
# endpoint returns no pricing, so re-check this table against the console before the demo.
PRICES_PER_M: dict[Flavor, tuple[float, float]] = {
    Flavor.NANO: (0.05, 0.20),
    Flavor.SUPER: (0.08, 0.40),
    Flavor.ULTRA: (0.50, 2.20),
}

# How each flavor is recognised in the live model list (case-insensitive).
_PATTERNS: dict[Flavor, str] = {
    Flavor.NANO: r"nemotron-3-nano",
    Flavor.SUPER: r"nemotron-3-super",
    Flavor.ULTRA: r"nemotron-3-ultra",
}

CACHE_PATH = Path(".cache/models.json")


class ModelResolutionError(RuntimeError):
    pass


class SpendCapExceeded(RuntimeError):
    pass


def resolve_ids(available: list[str]) -> dict[Flavor, str]:
    """Map flavors to live model IDs. Fails loudly on missing or ambiguous matches."""
    resolved: dict[Flavor, str] = {}
    for flavor, pattern in _PATTERNS.items():
        matches = [
            m for m in available
            if re.search(pattern, m, re.IGNORECASE) and not m.lower().endswith("-fast")
        ]
        if len(matches) != 1:
            raise ModelResolutionError(
                f"Expected exactly one base model for {flavor.value} "
                f"(pattern {pattern!r}), found {matches or 'none'}. Available: {available}"
            )
        resolved[flavor] = matches[0]
    return resolved


def estimate_cost(flavor: Flavor, tokens_in: int, tokens_out: int) -> float:
    price_in, price_out = PRICES_PER_M[flavor]
    return (tokens_in * price_in + tokens_out * price_out) / 1_000_000


@dataclass
class Completion:
    text: str
    record: ProvenanceRecord


class ModelRouter:
    def __init__(self, settings: Settings, log: ProvenanceLog):
        self.settings = settings
        self.log = log
        self.client = AsyncOpenAI(
            base_url=TOKEN_FACTORY_BASE_URL, api_key=settings.nebius_api_key
        )
        self._ids: dict[Flavor, str] | None = None

    async def model_ids(self, refresh: bool = False) -> dict[Flavor, str]:
        if self._ids and not refresh:
            return self._ids
        if not refresh and CACHE_PATH.exists():
            cached = json.loads(CACHE_PATH.read_text())
            self._ids = {Flavor(k): v for k, v in cached.items()}
            return self._ids
        available = [m.id for m in (await self.client.models.list()).data]
        self._ids = resolve_ids(available)
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps({f.value: i for f, i in self._ids.items()}, indent=2))
        return self._ids

    async def complete(
        self,
        stage: str,
        messages: list[dict],
        *,
        flavor: Flavor | None = None,
        fast: bool = False,
        temperature: float = 0.6,
        max_tokens: int | None = None,
        sources: list[str] | None = None,
        parents: list[str] | None = None,
    ) -> Completion:
        if self.log.total_cost_usd >= self.settings.spend_cap_usd:
            raise SpendCapExceeded(
                f"Logged spend ${self.log.total_cost_usd:.4f} reached cap "
                f"${self.settings.spend_cap_usd:.2f}"
            )
        flavor = flavor or STAGE_POLICY[stage]
        model = (await self.model_ids())[flavor] + ("-fast" if fast else "")

        start = time.perf_counter()
        resp = await self.client.chat.completions.create(
            model=model, messages=messages, temperature=temperature, max_tokens=max_tokens
        )
        latency = time.perf_counter() - start

        text = (resp.choices[0].message.content or "").strip()
        usage = resp.usage
        tokens_in = usage.prompt_tokens if usage else 0
        tokens_out = usage.completion_tokens if usage else 0
        record = self.log.add(ProvenanceRecord(
            kind="model",
            stage=stage,
            summary=text[:120].replace("\n", " "),
            inputs={"messages": messages, "temperature": temperature, "fast": fast},
            outputs={"text": text},
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=estimate_cost(flavor, tokens_in, tokens_out),
            latency_s=latency,
            sources=sources or [],
            parents=parents or [],
        ))
        return Completion(text=text, record=record)
