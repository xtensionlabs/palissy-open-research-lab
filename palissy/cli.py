"""CLI: run one research question through the full pipeline."""

import argparse
import asyncio
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


def main() -> None:
    parser = argparse.ArgumentParser(prog="palissy")
    parser.add_argument("question", help="Research question")
    parser.add_argument("--executor", choices=["contree", "local"], default="contree")
    parser.add_argument("-y", "--yes", action="store_true",
                        help="Auto-approve every gate (decisions are still recorded)")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(run(args.question, args.executor, args.yes))


if __name__ == "__main__":
    main()
