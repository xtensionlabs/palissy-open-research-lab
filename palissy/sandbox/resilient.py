"""Optional graceful degradation: use the local fallback only if ConTree itself errors.

Off by default. The local executor is not isolated, so on a public demo it must be an explicit
operator choice (PALISSY_ALLOW_LOCAL_FALLBACK=1). Results carry backend="local-fallback", so
provenance and the notebook never hide that the substitution happened.
"""

import logging

from .base import Branch, Checkpoint, ExecResult, Executor, Job

log = logging.getLogger("palissy.sandbox")


class ResilientExecutor:
    def __init__(self, primary: Executor, fallback: Executor):
        self.primary, self.fallback = primary, fallback
        self.name = primary.name
        self.degraded = False

    def _degrade(self, exc: Exception) -> None:
        log.warning("primary executor %s failed (%s); using %s",
                    self.primary.name, exc, self.fallback.name)
        self.degraded = True

    async def run(self, code: str, *, args: list[str] | None = None,
                  timeout: int = 120) -> ExecResult:
        if not self.degraded:
            try:
                return await self.primary.run(code, args=args, timeout=timeout)
            except Exception as exc:  # infrastructure failure, not a failing experiment
                self._degrade(exc)
        return await self.fallback.run(code, args=args, timeout=timeout)

    async def checkpoint(self, code: str) -> Checkpoint:
        if not self.degraded:
            try:
                return await self.primary.checkpoint(code)
            except Exception as exc:
                self._degrade(exc)
        return await self.fallback.checkpoint(code)

    async def clean_checkpoint(self, code: str) -> Checkpoint:
        return await (self.fallback if self.degraded else self.primary).clean_checkpoint(code)

    async def run_branches(self, ckpt: Checkpoint, jobs: list[Job], **kw) -> list[Branch]:
        if not self.degraded and ckpt.backend == self.primary.name:
            try:
                return await self.primary.run_branches(ckpt, jobs, **kw)
            except Exception as exc:
                self._degrade(exc)
        if ckpt.backend != self.fallback.name:  # a primary snapshot means nothing to the fallback
            ckpt = await self.fallback.checkpoint(ckpt.code)
        return await self.fallback.run_branches(ckpt, jobs, **kw)

    async def close(self) -> None:
        for ex in (self.primary, self.fallback):
            close = getattr(ex, "close", None)
            if close:
                await close()

    async def fork(self, branch: str) -> None:
        if not self.degraded:
            try:
                return await self.primary.fork(branch)
            except Exception:
                self.degraded = True
        await self.fallback.fork(branch)

    async def rollback(self, branch: str | None = None) -> None:
        if not self.degraded:
            try:
                return await self.primary.rollback(branch)
            except Exception:
                self.degraded = True
        await self.fallback.rollback(branch)
