"""ConTree executor via the `contree` CLI (verified against the live API on 2026-09-30).

Behaviours confirmed by hand, which this module relies on:
  - every non-disposable `run` becomes a checkpoint in the session history
  - `session branch X` + `checkout X` forks from the current checkpoint; files written on the
    branch are absent after `checkout main` (real filesystem isolation, not just bookkeeping)
  - a command's exit code is propagated by `run`; `-L error` keeps stderr free of CLI log lines
  - `python:3.12` has no numpy, so a tagged base image with numpy is built once and reused
  - `cd /work` fails on a fresh image; attaching a file with `-F host:/work/x` creates the dir
  - a timed-out `run` exits 127 or a wrapped -1 (mapped to 124 to match the local executor)
"""

import asyncio
import tempfile
from pathlib import Path

from .base import DEFAULT_TIMEOUT_S, ExecResult, timed

PUBLIC_IMAGE = "tag:python:3.12"
BASE_TAG = "palissy/base/python:3.12-numpy"
WORKDIR = "/work"
SCRIPT = f"{WORKDIR}/experiment.py"


class ContreeError(RuntimeError):
    pass


class ContreeExecutor:
    name = "contree"

    def __init__(self, session_key: str, base_branch: str = "main"):
        self.session = session_key
        self.base_branch = base_branch
        self._ready = False

    async def _cli(self, *args: str, timeout: int = 300, cwd: str | None = None
                   ) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_exec(
            "contree", "-L", "error", "-S", self.session, *args, cwd=cwd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return 124, "", f"contree CLI timed out after {timeout}s"
        return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")

    async def _base_image_exists(self) -> bool:
        rc, out, _ = await self._cli("images", f"--prefix={BASE_TAG}")
        return rc == 0 and BASE_TAG in out

    async def _ensure_session(self) -> None:
        """Start the session from the tagged numpy base image, building it on first use."""
        if self._ready:
            return
        if await self._base_image_exists():
            rc, _, err = await self._cli("use", f"tag:{BASE_TAG}")
            if rc != 0:
                raise ContreeError(f"contree use failed: {err.strip()}")
        else:
            for args in (("use", PUBLIC_IMAGE), ("run", "-t", "300", "--", "pip", "install",
                                                 "numpy"), ("tag", BASE_TAG)):
                rc, _, err = await self._cli(*args, timeout=400)
                if rc != 0:
                    raise ContreeError(f"contree {' '.join(args)} failed: {err.strip()}")
        self._ready = True

    async def run(self, code: str, *, args: list[str] | None = None,
                  timeout: int = DEFAULT_TIMEOUT_S) -> ExecResult:
        await self._ensure_session()
        start = timed()
        with tempfile.TemporaryDirectory(prefix="palissy_", ignore_cleanup_errors=True) as tmp:
            (Path(tmp) / "experiment.py").write_text(code, encoding="utf-8")
            # Relative host path + cwd=tmp avoids ':' in a Windows drive letter clashing with
            # the host_path:instance_path attachment syntax.
            rc, out, err = await self._cli(
                "run", "-t", str(timeout), "-F", f"experiment.py:{SCRIPT}", "--",
                "python", SCRIPT, *(args or []), timeout=timeout + 60, cwd=tmp)
        duration = timed() - start
        # A timed-out run surfaces as 127 or as a wrapped -1 (4294967295 on Windows). Require
        # the wall clock to have reached the limit so a real "command not found" 127 is kept.
        if (rc == 127 or rc > 255 or rc < 0) and duration >= timeout - 1:
            rc, err = 124, err or f"timeout after {timeout}s"
        return ExecResult(stdout=out, stderr=err, exit_code=rc, duration_s=duration,
                          backend=self.name)

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
