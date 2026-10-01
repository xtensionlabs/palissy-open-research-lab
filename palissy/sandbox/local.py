"""FALLBACK executor: a host subprocess with a timeout and a scratch directory.

This is NOT isolated. It exists so the pipeline stays demoable if ConTree is unavailable
(CLAUDE.md, Non-Essential Goals and Fallbacks). Results are labelled backend="local-fallback"
in provenance so the substitution is never hidden. There are no snapshots here: a checkpoint
just holds the code, and every branch gets its own scratch directory.
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

from .base import (DEFAULT_TIMEOUT_S, HARNESS_SOURCE, Branch, Checkpoint, ExecResult, Job,
                   gather_limited, sha, timed)


class LocalExecutor:
    name = "local-fallback"

    async def _exec(self, code: str, argv: list[str], env_extra: dict[str, str],
                    timeout: int, harness: bool) -> ExecResult:
        start = timed()
        with tempfile.TemporaryDirectory(prefix="palissy_", ignore_cleanup_errors=True) as tmp:
            script = Path(tmp) / "experiment.py"
            script.write_text(code, encoding="utf-8")
            cmd = [sys.executable, str(script), *argv]
            if harness:
                (Path(tmp) / "harness.py").write_text(HARNESS_SOURCE, encoding="utf-8")
                cmd = [sys.executable, str(Path(tmp) / "harness.py"), str(script), *argv]
            proc = await asyncio.create_subprocess_exec(
                *cmd, cwd=tmp, env={**os.environ, **env_extra},
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            try:
                out, err = await asyncio.wait_for(proc.communicate(), timeout)
                code_ = proc.returncode
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()  # release the cwd handle so Windows can delete the temp dir
                out, err, code_ = b"", f"timeout after {timeout}s".encode(), 124
        return ExecResult(
            stdout=out.decode(errors="replace"), stderr=err.decode(errors="replace"),
            exit_code=code_ if code_ is not None else 1,
            duration_s=timed() - start, backend=self.name,
        )

    async def run(self, code: str, *, args: list[str] | None = None,
                  timeout: int = DEFAULT_TIMEOUT_S) -> ExecResult:
        return await self._exec(code, args or [], {}, timeout, harness=False)

    async def checkpoint(self, code: str) -> Checkpoint:
        return Checkpoint(backend=self.name, code=code, code_hash=sha(code))

    async def clean_checkpoint(self, code: str) -> Checkpoint:
        return await self.checkpoint(code)

    async def run_branches(self, ckpt: Checkpoint, jobs: list[Job], *, concurrency: int = 4,
                           timeout: int = DEFAULT_TIMEOUT_S, clean: bool = False
                           ) -> list[Branch]:
        async def one(job: Job) -> Branch:
            r = await self._exec(ckpt.code, [job.arm],
                                 {"PALISSY_SEED_OFFSET": str(job.seed_offset)}, timeout,
                                 harness=True)
            return Branch(job, r)
        return await gather_limited((one(j) for j in jobs), concurrency)

    async def fork(self, branch: str) -> None:
        return None

    async def rollback(self, branch: str | None = None) -> None:
        return None
