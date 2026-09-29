"""FALLBACK executor: a host subprocess with a timeout and a scratch directory.

This is NOT isolated. It exists so the pipeline stays demoable if ConTree is unavailable
(CLAUDE.md, Non-Essential Goals and Fallbacks). Results are labelled backend="local-fallback"
in provenance so the substitution is never hidden. Fork/rollback are no-ops here.
"""

import asyncio
import sys
import tempfile
from pathlib import Path

from .base import ExecResult, timed


class LocalExecutor:
    name = "local-fallback"

    async def run(self, code: str, *, timeout: int = 120) -> ExecResult:
        start = timed()
        with tempfile.TemporaryDirectory(prefix="palissy_", ignore_cleanup_errors=True) as tmp:
            script = Path(tmp) / "experiment.py"
            script.write_text(code, encoding="utf-8")
            proc = await asyncio.create_subprocess_exec(
                sys.executable, str(script), cwd=tmp,
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

    async def fork(self, branch: str) -> None:
        return None

    async def rollback(self, branch: str | None = None) -> None:
        return None
