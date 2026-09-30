"""Optional graceful degradation: use the local fallback only if ConTree itself errors.

Off by default. The local executor is not isolated, so on a public demo it must be an explicit
operator choice (PALISSY_ALLOW_LOCAL_FALLBACK=1). Results carry backend="local-fallback", so
provenance and the notebook never hide that the substitution happened.
"""

import logging

from .base import ExecResult, Executor

log = logging.getLogger("palissy.sandbox")


class ResilientExecutor:
    def __init__(self, primary: Executor, fallback: Executor):
        self.primary, self.fallback = primary, fallback
        self.name = primary.name
        self.degraded = False

    async def run(self, code: str, *, timeout: int = 120) -> ExecResult:
        if not self.degraded:
            try:
                return await self.primary.run(code, timeout=timeout)
            except Exception as exc:  # infrastructure failure, not a failing experiment
                log.warning("primary executor %s failed (%s); using %s",
                            self.primary.name, exc, self.fallback.name)
                self.degraded = True
        return await self.fallback.run(code, timeout=timeout)

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
