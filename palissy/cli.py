"""Milestone 1 entry point: question -> search -> hypothesis -> sandbox run -> provenance log."""

import argparse
import asyncio
import sys
import time

from .config import load_settings
from .literature import Literature
from .models import ModelRouter
from .provenance import ProvenanceLog
from .sandbox import ContreeExecutor, LocalExecutor, log_execution
from .stages.hypothesis import design_experiment, propose_hypothesis


def make_executor(kind: str):
    if kind == "local":
        return LocalExecutor()
    return ContreeExecutor(session_key=f"agent_palissy_{int(time.time())}")


async def run(question: str, executor_kind: str, yes: bool) -> None:
    settings = load_settings(need_tavily=True)
    log = ProvenanceLog(f"data/provenance_{int(time.time())}.jsonl")
    router = ModelRouter(settings, log)
    lit = Literature(settings.tavily_api_key, log)

    print(f"Question: {question}\n")
    results, lit_rec = await lit.search(question)
    print(f"Literature: {len(results)} sources")

    h = await propose_hypothesis(router, question, results, lit_rec.id)
    print(f"\nHypothesis: {h.hypothesis}\nPrediction: {h.prediction}\n")

    code, code_rec = await design_experiment(router, h)
    print(f"--- experiment code ---\n{code}\n-----------------------")

    # Human gate: nothing executes without approval.
    if not yes and input("Run this experiment? [y/N] ").strip().lower() != "y":
        print("Rejected. Nothing was executed.")
    else:
        executor = make_executor(executor_kind)
        result = await executor.run(code)
        log_execution(log, code, result, parents=[code_rec.id])
        print(f"\n[{result.backend}] exit={result.exit_code}\n{result.stdout}{result.stderr}")

    print("\n=== Provenance ===")
    print(log.render())


def main() -> None:
    parser = argparse.ArgumentParser(prog="palissy")
    parser.add_argument("question", help="Research question")
    parser.add_argument("--executor", choices=["contree", "local"], default="contree")
    parser.add_argument("-y", "--yes", action="store_true", help="Skip the approval prompt")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(run(args.question, args.executor, args.yes))


if __name__ == "__main__":
    main()
