"""Human-in-the-loop gates. A gate blocks the pipeline until a person decides.

Actions: approve (proceed), reject (regenerate with the reason), modify (person supplies the
replacement), inject (person adds knowledge; regenerate with it).
"""

import asyncio
from dataclasses import dataclass
from typing import Literal, Protocol

Action = Literal["approve", "reject", "modify", "inject"]


@dataclass
class Decision:
    action: Action
    payload: str | None = None


class Gate(Protocol):
    async def review(self, stage: str, title: str, proposal: dict) -> Decision: ...


class AutoApproveGate:
    """For unattended runs and tests. Decisions are still recorded as provenance."""

    async def review(self, stage: str, title: str, proposal: dict) -> Decision:
        return Decision("approve")


class ScriptedGate:
    """Replays a fixed list of decisions in order (tests, reproducible demos)."""

    def __init__(self, decisions: list[Decision]):
        self._decisions = list(decisions)
        self.seen: list[tuple[str, dict]] = []

    async def review(self, stage: str, title: str, proposal: dict) -> Decision:
        self.seen.append((stage, proposal))
        return self._decisions.pop(0) if self._decisions else Decision("approve")


class ApiGate:
    """Blocks the pipeline on an asyncio future until the HTTP API delivers a decision.

    The pending gate is also persisted, so a page refresh can rediscover it. `registry` maps
    gate id -> future and is shared with the API process that resolves them.
    """

    def __init__(self, store, project_id: str, registry: dict, get_cycle=lambda: 1):
        self.store, self.project_id = store, project_id
        self.registry, self.get_cycle = registry, get_cycle

    async def review(self, stage: str, title: str, proposal: dict) -> Decision:
        gid = self.store.create_gate(self.project_id, self.get_cycle(), stage, title, proposal)
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self.registry[gid] = future
        try:
            return await future
        finally:
            self.registry.pop(gid, None)
            self.store.resolve_gate(gid)


class CliGate:
    async def review(self, stage: str, title: str, proposal: dict) -> Decision:
        print(f"\n=== Gate: {title} ===")
        for key, value in proposal.items():
            print(f"{key}:\n{value}\n")
        while True:
            choice = (await asyncio.to_thread(
                input, "[a]pprove  [r]eject  [m]odify  [i]nject knowledge > ")).strip().lower()
            if choice in ("a", "approve"):
                return Decision("approve")
            if choice in ("r", "reject"):
                reason = await asyncio.to_thread(input, "Why? > ")
                return Decision("reject", reason)
            if choice in ("m", "modify"):
                text = await asyncio.to_thread(input, "Replacement (single line) > ")
                return Decision("modify", text)
            if choice in ("i", "inject"):
                text = await asyncio.to_thread(input, "Knowledge to add > ")
                return Decision("inject", text)
