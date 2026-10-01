"""Executor interface. ConTree is the primary implementation; the local one is a fallback."""

import time
from dataclasses import dataclass
from typing import Protocol

from ..provenance import ProvenanceLog, ProvenanceRecord

DEFAULT_TIMEOUT_S = 120


@dataclass
class ExecResult:
    stdout: str
    stderr: str
    exit_code: int
    duration_s: float
    backend: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


class Executor(Protocol):
    name: str

    async def run(self, code: str, *, args: list[str] | None = None,
                  timeout: int = DEFAULT_TIMEOUT_S) -> ExecResult: ...

    async def fork(self, branch: str) -> None:
        """Start a variant branch from the current checkpoint."""

    async def rollback(self, branch: str | None = None) -> None:
        """Abandon the current branch and return to the last good checkpoint."""


def log_execution(
    log: ProvenanceLog, code: str, result: ExecResult, parents: list[str] | None = None,
    args: list[str] | None = None,
) -> ProvenanceRecord:
    label = f" {' '.join(args)}" if args else ""
    return log.add(ProvenanceRecord(
        kind="sandbox",
        stage="execution",
        summary=f"[{result.backend}{label}] exit={result.exit_code}: "
                f"{(result.stdout or result.stderr)[:100]!r}",
        inputs={"code": code, "args": args or []},
        outputs={"stdout": result.stdout, "stderr": result.stderr,
                 "exit_code": result.exit_code},
        latency_s=result.duration_s,
        parents=parents or [],
    ))


def timed() -> float:
    return time.perf_counter()
