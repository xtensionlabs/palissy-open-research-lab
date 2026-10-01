"""CLI: run one research question through the full pipeline."""

import argparse
import asyncio
import json
import sys
import time

from .config import load_settings
from .db import Store
from .gates import AutoApproveGate, CliGate
from .literature import Literature
from .models import ModelRouter
from .pipeline import Pipeline
from .provenance import ProvenanceLog
from .sandbox import ContreeExecutor, LocalExecutor


def make_executor(kind: str):
    if kind == "local":
        return LocalExecutor()
    return ContreeExecutor(session_key=f"agent_palissy_{int(time.time())}")


async def run(question: str, executor_kind: str, auto: bool) -> None:
    settings = load_settings(need_tavily=True)
    store = Store(settings.db_path)
    pid = store.create_project(question)
    log = ProvenanceLog(f"data/provenance_{pid}.jsonl", store=store, project_id=pid)
    pipeline = Pipeline(
        router=ModelRouter(settings, log),
        literature=Literature(settings.tavily_api_key, log),
        executor=make_executor(executor_kind),
        gate=AutoApproveGate() if auto else CliGate(),
        store=store, log=log,
    )
    print(f"Project {pid}: {question}")
    state = await pipeline.run(question)
    print(f"\nVerdict: {state.verdict}")
    for reason in state.verdict_reasons:
        print(f"  - {reason}")
    print(state.findings)
    print(f"Notebook: {state.notebook_path}")
    print(f"Spend: ${store.project_cost(pid):.4f}\n\n=== Provenance ===\n{log.render()}")


async def replay(pid: str) -> int:
    """Re-run a finished project's recorded runs in clean sandboxes and compare the output."""
    settings = load_settings()
    store = Store(settings.db_path)
    row = store.get_project(pid)
    state = json.loads(row["state"]) if row and row["state"] else None
    if not state or not state.get("branches"):
        print(f"Project {pid} has no recorded runs to replay.")
        return 1
    kind = "local" if state.get("backend") == "local-fallback" else "contree"
    log = ProvenanceLog(f"data/provenance_{pid}.jsonl", store=store, project_id=pid)
    pipeline = Pipeline(router=None, literature=None, executor=make_executor(kind),
                        gate=AutoApproveGate(), store=store, log=log)
    out = await pipeline.replay(state)
    for i in out["items"]:
        print(f"  {'match   ' if i['match'] else 'DIFFERS '} {i['id']:<14} {i['actual']}")
    print(f"{out['matched']} of {out['total']} runs reproduced in {out['duration_s']}s "
          f"on {out['backend']} from {out['base']}")
    return 0 if out["matched"] == out["total"] else 2


def main() -> None:
    parser = argparse.ArgumentParser(prog="palissy")
    parser.add_argument("question", nargs="?", help="Research question")
    parser.add_argument("--replay", metavar="PROJECT_ID",
                        help="Re-run a finished project's runs in clean sandboxes and compare")
    parser.add_argument("--executor", choices=["contree", "local"], default="contree")
    parser.add_argument("-y", "--yes", action="store_true",
                        help="Auto-approve every gate (decisions are still recorded)")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if args.replay:
        sys.exit(asyncio.run(replay(args.replay)))
    if not args.question:
        parser.error("give a research question, or --replay PROJECT_ID")
    asyncio.run(run(args.question, args.executor, args.yes))


if __name__ == "__main__":
    main()
