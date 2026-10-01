"""ConTree executor via the `contree` CLI (verified against the live API on 2026-09-30/10-01).

Behaviours confirmed by hand, which this module relies on:
  - every non-disposable `run` becomes a checkpoint in the session history; the checkpoint's
    image id is readable from `-o json session` (`current_image`)
  - `run --use <image> -D` starts a throwaway branch from any image id; several of them, each
    under its own session key, run in parallel with no shared state (3 at once took the
    wall time of 1)
  - `-o json run` reports the operation uuid, exit code, stdout/stderr and an explicit
    `timed_out` flag, so a timeout is no longer inferred from exit 127 / a wrapped -1
  - `python:3.12` has no numpy, so a tagged base image with numpy is built once and reused
  - `cd /work` fails on a fresh image; attaching a file with `-F host:/work/x` creates the dir
  - the Beta limit is 50 simultaneous operations; `concurrency` keeps well under it
"""

import asyncio
import json
import tempfile
from pathlib import Path

from .base import (DEFAULT_TIMEOUT_S, HARNESS_SOURCE, Branch, Checkpoint, ExecResult, Job,
                   gather_limited, sha, timed)

PUBLIC_IMAGE = "tag:python:3.12"
BASE_TAG = "palissy/base/python:3.12-numpy"
WORKDIR = "/work"
SCRIPT = f"{WORKDIR}/experiment.py"
HARNESS = f"{WORKDIR}/harness.py"


class ContreeError(RuntimeError):
    pass


class ContreeExecutor:
    name = "contree"

    def __init__(self, session_key: str, base_branch: str = "main"):
        self.session = session_key
        self.base_branch = base_branch
        self._ready = False
        self._n = 0

    async def _cli(self, *args: str, timeout: int = 300, cwd: str | None = None,
                   session: str | None = None) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_exec(
            "contree", "-L", "error", "-S", session or self.session, *args, cwd=cwd,
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

    # --- single run (kept for simple use and the CLI) -----------------------------------

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
        # Without -o json a timeout surfaces as 127 or a wrapped -1; require the wall clock to
        # have reached the limit so a real "command not found" 127 is kept.
        if (rc == 127 or rc > 255 or rc < 0) and duration >= timeout - 1:
            rc, err = 124, err or f"timeout after {timeout}s"
        return ExecResult(stdout=out, stderr=err, exit_code=rc, duration_s=duration,
                          backend=self.name)

    # --- checkpoint and branches --------------------------------------------------------

    async def checkpoint(self, code: str) -> Checkpoint:
        """Attach the script and harness once, so every branch forks from the same image."""
        await self._ensure_session()
        with tempfile.TemporaryDirectory(prefix="palissy_", ignore_cleanup_errors=True) as tmp:
            (Path(tmp) / "experiment.py").write_text(code, encoding="utf-8")
            (Path(tmp) / "harness.py").write_text(HARNESS_SOURCE, encoding="utf-8")
            rc, _, err = await self._cli(
                "run", "-F", f"experiment.py:{SCRIPT}", "-F", f"harness.py:{HARNESS}", "--",
                "true", cwd=tmp)
        if rc != 0:
            raise ContreeError(f"checkpoint failed: {err.strip()}")
        rc, out, err = await self._cli("-o", "json", "session")
        try:
            image = json.loads(out)["current_image"]
        except (ValueError, KeyError, TypeError) as exc:
            raise ContreeError(f"could not read the checkpoint image: {out[:200]!r} {err}") from exc
        return Checkpoint(backend=self.name, code=code, code_hash=sha(code), image=image,
                          base=f"tag:{BASE_TAG}", session=self.session)

    async def clean_checkpoint(self, code: str) -> Checkpoint:
        return Checkpoint(backend=self.name, code=code, code_hash=sha(code),
                          base=f"tag:{BASE_TAG}", session=self.session)

    def _result(self, rc: int, out: str, err: str, wall: float, timeout: int) -> ExecResult:
        try:
            data = json.loads(out)
        except ValueError:
            data = None
        if not isinstance(data, dict) or "exit_code" not in data:
            # The CLI or API failed before the command ran: infrastructure, not an experiment
            # failure, so let ResilientExecutor decide what to do.
            raise ContreeError(f"no result from contree (rc={rc}): {(err or out)[:300].strip()}")
        state = ((data.get("metadata") or {}).get("result") or {}).get("state") or {}
        code = data.get("exit_code")
        stderr = data.get("stderr") or ""
        if state.get("timed_out"):
            code, stderr = 124, stderr or f"timeout after {timeout}s"
        elif code is None:
            code, stderr = 1, stderr or data.get("error") or "operation failed"
        return ExecResult(stdout=data.get("stdout") or "", stderr=stderr, exit_code=int(code),
                          duration_s=wall, backend=self.name, op_id=str(data.get("uuid") or ""))

    async def _branch(self, job: Job, key: str, image: str, attach: str | None,
                      timeout: int) -> Branch:
        args = ["-o", "json", "run", "--use", image, "-D", "-t", str(timeout),
                "-e", f"PALISSY_SEED_OFFSET={job.seed_offset}"]
        if attach:  # a clean base image has nothing in /work yet
            args += ["-F", f"experiment.py:{SCRIPT}", "-F", f"harness.py:{HARNESS}"]
        args += ["--", "python", HARNESS, SCRIPT, job.arm]
        last: Exception | None = None
        for _ in range(2):  # one retry for a transient CLI/API failure
            start = timed()
            rc, out, err = await self._cli(*args, timeout=timeout + 60, session=key, cwd=attach)
            try:
                return Branch(job, self._result(rc, out, err, timed() - start, timeout), key)
            except ContreeError as exc:
                last = exc
        raise last  # type: ignore[misc]

    async def run_branches(self, ckpt: Checkpoint, jobs: list[Job], *, concurrency: int = 4,
                           timeout: int = DEFAULT_TIMEOUT_S, clean: bool = False
                           ) -> list[Branch]:
        await self._ensure_session()
        keys = []
        for _ in jobs:
            self._n += 1
            keys.append(f"{self.session}_b{self._n}")
        with tempfile.TemporaryDirectory(prefix="palissy_", ignore_cleanup_errors=True) as tmp:
            attach = None
            if clean:
                (Path(tmp) / "experiment.py").write_text(ckpt.code, encoding="utf-8")
                (Path(tmp) / "harness.py").write_text(HARNESS_SOURCE, encoding="utf-8")
                attach = tmp
            image = ckpt.base if clean else ckpt.image
            try:
                results = await gather_limited(
                    (self._guard(self._branch(j, k, image, attach, timeout))
                     for j, k in zip(jobs, keys)), concurrency)
            finally:
                # Branch sessions are throwaway: delete them so they don't pile up.
                await self._cli("session", "delete", "-f", *keys)
        errors = [r for r in results if isinstance(r, Exception)]
        if errors:
            raise errors[0]
        return results

    @staticmethod
    async def _guard(coro):
        """Turn an exception into a value so one failed branch can't orphan its siblings."""
        try:
            return await coro
        except Exception as exc:  # noqa: BLE001 - re-raised by the caller after all finish
            return exc

    async def close(self) -> None:
        """Delete this executor's own session, so finished runs don't leave sessions behind."""
        if self._ready:
            await self._cli("session", "delete", "-f", self.session)
            self._ready = False

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
