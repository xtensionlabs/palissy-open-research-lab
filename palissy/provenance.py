"""Provenance records: every model/tool call emits one. Differentiator #4 rests on this."""

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ProvenanceRecord:
    kind: str  # "model" | "search" | "extract" | "sandbox" | "decision"
    stage: str
    summary: str
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    model: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    latency_s: float = 0.0
    sources: list[str] = field(default_factory=list)
    parents: list[str] = field(default_factory=list)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    ts: float = field(default_factory=time.time)


class ProvenanceLog:
    """In-memory log, optionally mirrored to a JSONL file. SQLite comes in Milestone 2."""

    def __init__(self, path: str | Path | None = None, *, store=None,
                 project_id: str | None = None):
        self.records: list[ProvenanceRecord] = []
        self.path = Path(path) if path else None
        self.store = store
        self.project_id = project_id
        self.cycle = 1
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def add(self, record: ProvenanceRecord) -> ProvenanceRecord:
        self.records.append(record)
        if self.store and self.project_id:
            self.store.add_record(record, self.project_id, self.cycle)
        if self.path:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(record), default=str) + "\n")
        return record

    @property
    def total_cost_usd(self) -> float:
        return sum(r.cost_usd for r in self.records)

    def render(self) -> str:
        lines = []
        for r in self.records:
            model = f" [{r.model}]" if r.model else ""
            lines.append(
                f"{r.id} {r.kind:<7} {r.stage:<18}{model} "
                f"in={r.tokens_in} out={r.tokens_out} ${r.cost_usd:.5f} {r.latency_s:.2f}s"
                f"\n    {r.summary}"
            )
            for s in r.sources:
                lines.append(f"    source: {s}")
        lines.append(f"TOTAL ${self.total_cost_usd:.5f}")
        return "\n".join(lines)
