"""ConTree executor via the `contree` CLI, following `contree agent` (CLI manual).

UNTESTED: written against the manual while Sandboxes access was returning 403. Verify each
command once access is enabled, and record what differs in FEEDBACK.md.

Mapping: one ConTree session per project; each run creates a checkpoint; fork = new session
branch; rollback = checkout the base branch.
"""

import asyncio
import tempfile
from pathlib import Path

from .base import ExecResult, timed

BASE_IMAGE = "tag:python:3.12"


class ContreeError(RuntimeError):
    pass


class ContreeExecutor:
    name = "contree"

    def __init__(self, session_key: str, image: str = BASE_IMAGE, base_branch: str = "main"):
        self.session = session_key
        self.image = image
        self.base_branch = base_branch
        self._ready = False

    async def _cli(self, *args: str, timeout: int = 300) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_exec(
            "contree", "-S", self.session, *args,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
        return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")

    async def _ensure_session(self) -> None:
        if self._ready:
            return
        for args in (("use", self.image), ("cd", "/work")):
            rc, _, err = await self._cli(*args)
            if rc != 0:
                raise ContreeError(f"contree {' '.join(args)} failed: {err.strip()}")
        self._ready = True

    async def run(self, code: str, *, timeout: int = 120) -> ExecResult:
        await self._ensure_session()
        start = timed()
        # Ship the script as a session file, then run it: one mutating step per run.
        with tempfile.TemporaryDirectory(prefix="palissy_") as tmp:
            script = Path(tmp) / "experiment.py"
            script.write_text(code, encoding="utf-8")
            rc, _, err = await self._cli("file", "put", str(script), "/work/experiment.py")
            if rc != 0:
                raise ContreeError(f"contree file put failed: {err.strip()}")
        rc, out, err = await self._cli("run", "--", "python", "/work/experiment.py",
                                       timeout=timeout)
        return ExecResult(stdout=out, stderr=err, exit_code=rc,
                          duration_s=timed() - start, backend=self.name)

    async def fork(self, branch: str) -> None:
        await self._ensure_session()
        for args in (("session", "branch", branch), ("session", "checkout", branch)):
            rc, _, err = await self._cli(*args)
            if rc != 0:
                raise ContreeError(f"contree {' '.join(args)} failed: {err.strip()}")

    async def rollback(self, branch: str | None = None) -> None:
        rc, _, err = await self._cli("session", "checkout", self.base_branch)
        if rc != 0:
            raise ContreeError(f"contree session checkout failed: {err.strip()}")
        if branch:
            await self._cli("session", "branch", "--delete", branch)
