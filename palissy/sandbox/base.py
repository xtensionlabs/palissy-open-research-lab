"""Executor interface. ConTree is the primary implementation; the local one is a fallback.

An experiment runs as a grid of branches: `checkpoint` snapshots the sandbox with the script
attached once, and `run_branches` forks every (arm, replicate) job from that snapshot, so each
branch starts from the same state and none can affect another.
"""

import asyncio
import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from ..provenance import ProvenanceLog, ProvenanceRecord

DEFAULT_TIMEOUT_S = 120
SEED_STRIDE = 1009  # replicate k shifts every seed in the script by k * SEED_STRIDE
HARNESS_SOURCE = (Path(__file__).parent / "harness.py").read_text(encoding="utf-8")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


@dataclass
class ExecResult:
    stdout: str
    stderr: str
    exit_code: int
    duration_s: float
    backend: str
    op_id: str = ""  # the sandbox's own operation id, when it reports one

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


@dataclass(frozen=True)
class Job:
    arm: str
    rep: int

    @property
    def seed_offset(self) -> int:
        return self.rep * SEED_STRIDE

    @property
    def label(self) -> str:
        return f"{self.arm}#{self.rep + 1}"


@dataclass
class Checkpoint:
    """A sandbox snapshot with the script and harness attached. Replicates fork from it."""
    backend: str
    code: str
    code_hash: str
    image: str = ""  # sandbox image id; empty where the backend has no snapshots
    base: str = ""  # the clean image the snapshot was built from, used by replay
    session: str = ""


@dataclass
class Branch:
    job: Job
    result: ExecResult
    key: str = ""  # the branch's own sandbox session, so concurrent forks never share state


class Executor(Protocol):
    name: str

    async def run(self, code: str, *, args: list[str] | None = None,
                  timeout: int = DEFAULT_TIMEOUT_S) -> ExecResult: ...

    async def checkpoint(self, code: str) -> Checkpoint:
        """Snapshot the sandbox with the script attached."""

    async def clean_checkpoint(self, code: str) -> Checkpoint:
        """A checkpoint for `clean=True` runs: no sandbox call, just the code and the base
        image every branch will start from again."""

    async def run_branches(self, ckpt: Checkpoint, jobs: list[Job], *, concurrency: int = 4,
                           timeout: int = DEFAULT_TIMEOUT_S, clean: bool = False
                           ) -> list[Branch]:
        """Fork each job from the checkpoint and run them in parallel, at most `concurrency`
        at once. With `clean=True` start from the base image again instead of the snapshot
        (used by replay, to prove the result doesn't depend on leftover state)."""

    async def fork(self, branch: str) -> None:
        """Start a variant branch from the current checkpoint."""

    async def rollback(self, branch: str | None = None) -> None:
        """Abandon the current branch and return to the last good checkpoint."""


async def gather_limited(coros, concurrency: int):
    """Run awaitables with at most `concurrency` in flight; results keep input order."""
    sem = asyncio.Semaphore(max(1, concurrency))

    async def guarded(c):
        async with sem:
            return await c
    return await asyncio.gather(*(guarded(c) for c in coros))


def log_execution(
    log: ProvenanceLog, code: str, result: ExecResult, parents: list[str] | None = None,
    args: list[str] | None = None, meta: dict | None = None,
) -> ProvenanceRecord:
    label = f" {' '.join(args)}" if args else ""
    return log.add(ProvenanceRecord(
        kind="sandbox",
        stage="execution",
        summary=f"[{result.backend}{label}] exit={result.exit_code}: "
                f"{(result.stdout or result.stderr)[:100]!r}",
        inputs={"code": code, "args": args or [], **(meta or {})},
        outputs={"stdout": result.stdout, "stderr": result.stderr,
                 "exit_code": result.exit_code, "stdout_sha": sha(result.stdout),
                 "op_id": result.op_id},
        latency_s=result.duration_s,
        parents=parents or [],
    ))


def timed() -> float:
    return time.perf_counter()
