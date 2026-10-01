"""Reproducible .ipynb output. Written as plain nbformat-4 JSON (no nbformat dependency).

The code cell holds the exact script that ran; its recorded output is stored alongside, and the
provenance table at the end links every claim back to a record id.
"""

import json
from pathlib import Path

from .sandbox.base import HARNESS_SOURCE


def _g(x) -> str:
    return "–" if x is None or x == "" else f"{float(x):.4g}"


def _p(x) -> str:
    """The smallest p a permutation test can report is 1/(shuffles+1); don't print it as exact."""
    if x is None or x == "":
        return "–"
    return "< 0.0001" if float(x) < 1e-4 else f"{float(x):.3g}"


def _md(text: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": text.splitlines(keepends=True)}


def _code(text: str, stdout: str = "", stderr: str = "") -> dict:
    outputs = []
    if stdout:
        outputs.append({"output_type": "stream", "name": "stdout",
                        "text": stdout.splitlines(keepends=True)})
    if stderr:
        outputs.append({"output_type": "stream", "name": "stderr",
                        "text": stderr.splitlines(keepends=True)})
    return {"cell_type": "code", "metadata": {}, "execution_count": None,
            "outputs": outputs, "source": text.splitlines(keepends=True)}


def build_notebook(*, project_id: str, question: str, state, records: list[dict],
                   decisions: list[dict], total_cost: float) -> dict:
    sources = "\n".join(f"- [{r.get('title')}]({r.get('url')})" for r in state.literature)
    lessons_before = "\n".join(f"- {l}" for l in state.lessons_before) or "- (none)"
    lessons_after = "\n".join(f"- {l}" for l in state.lessons_after) or "- (none)"
    decision_lines = "\n".join(
        f"- `{d['stage']}`: **{d['action']}**" + (f" — {d['payload']}" if d["payload"] else "")
        for d in decisions) or "- (none)"
    prov_rows = ["| id | kind | stage | model | tokens in/out | cost (USD) | parents |",
                 "|---|---|---|---|---|---|---|"]
    for r in records:
        prov_rows.append(
            f"| `{r['id']}` | {r['kind']} | {r['stage']} | {r.get('model') or ''} | "
            f"{r['tokens_in']}/{r['tokens_out']} | {r['cost_usd']:.5f} | "
            f"{', '.join(f'`{p}`' for p in r['parents'])} |")

    t = state.triage or {}
    triage = ""
    if t and t.get("category") != "testable":
        triage = (f"\n\n**Question check: {t.get('label', t.get('category'))}** {t.get('reason', '')}"
                  + (f"\n\nOriginal question: *{state.original_question}*"
                     if state.original_question and state.original_question != question else "")
                  + ("\n\nThe researcher chose to continue knowingly."
                     if t.get("decision") == "continued" else ""))

    contract = state.contract or {}
    prereg = ("\n".join(f"| {k.replace('_', ' ')} | {v} |" for k, v in contract.items())
              if contract else "")
    prereg_md = (f"## Pre-registration\n\nCommitted before the run and frozen at approval "
                 f"(hash `{state.contract_hash}`). The verdict below is computed from it by "
                 f"rule, not by a model.\n\n| field | committed |\n|---|---|\n{prereg}"
                 if contract else "## Pre-registration\n\nNone was committed "
                 f"({state.contract_error or 'missing'}), so no verdict can be reported.")
    crit = state.critique or {}
    if crit:
        answers = "\n".join(f"- {'✓' if a.get('ok') else '✗'} **{k.replace('_', ' ')}**: "
                            f"{a.get('why', '')}" for k, a in crit.get("answers", {}).items())
        prereg_md += (f"\n\n**Design critic: {crit.get('level')}** (checked by "
                      f"{', '.join(crit.get('checked_by', []))}). {crit.get('summary', '')}"
                      f"\n\n{answers}")
        if crit.get("edited_after"):
            prereg_md += "\n\nThe researcher edited the code after this review."
        if crit.get("approved_over"):
            prereg_md += (f"\n\n**Run over the critic's {crit['approved_over']}.** Read the "
                          "verdict with that objection in mind.")

    names = {"treatment": "Treatment", "positive": "Positive control",
             "negative": "Negative control"}
    tally_rows = "\n".join(
        f"| {names.get(a, a)} | {t['ok']} of {t['total']} | {t['hits']} | "
        f"{_g(t['median_effect'])} | {_p(t['median_p'])} |"
        for a, t in (state.tally or {}).items())
    run_rows = "\n".join(
        f"| {b['id']} | {b['seed_offset']} | {b['status'].replace('_', ' ')}"
        f"{' (' + b['reason'] + ')' if b['reason'] else ''} | "
        f"{_g((b.get('result') or {}).get('effect'))} | "
        f"{_p((b.get('result') or {}).get('p_value'))} | "
        f"{(b.get('result') or {}).get('n', '–')} | "
        f"{_g((b.get('result') or {}).get('successes'))} |"
        for b in (state.branches or []))
    checks = "\n".join(f"- {'✓' if ch['passed'] else '✗'} **{ch['name']}**: {ch['detail']}"
                       for ch in state.checks)
    reasons = "\n".join(f"- {r}" for r in state.verdict_reasons)

    cells = [
        _md(f"# {question}\n\nPalissy project `{project_id}` · total model spend "
            f"**${total_cost:.4f}** · data: **{state.data_source}**\n\nGenerated with Nebius "
            f"Token Factory (Nemotron 3), ConTree sandboxes and Tavily.{triage}"),
        _md(f"## Literature\n\n{state.literature_summary}\n\n{sources}"),
        _md(f"## Hypothesis\n\n{state.hypothesis}\n\n**Prediction.** {state.prediction}\n\n"
            f"**Rationale.** {state.rationale}"
            + (f"\n\n**Phrasing warning.** {state.hypothesis_warning}"
               if state.hypothesis_warning else "")),
        _md(prereg_md),
        _md("## Experiment\n\nExecuted in: `" + state.backend + "`. Requires `numpy`. The script "
            "runs one arm per call. Each of the three arms ran "
            f"{state.replicates or 1} times as separate sandbox branches forked from one "
            "checkpoint" + (f" (image `{state.checkpoint.get('image')}`)"
                            if state.checkpoint.get("image") else "") + ", each with its own "
            "seed. The output below is the first run of each arm."
            + (" The code was repaired after a failed run." if state.repaired else "")),
        _code(state.code, state.stdout, state.stderr),
        _md("## Reproducing a run\n\nRun *k* of an arm shifts every integer seed in the script "
            "by `k * 1009` through a small harness, so each run differs but replays exactly:\n\n"
            "`PALISSY_SEED_OFFSET=<offset> python harness.py experiment.py <arm>`"),
        _code(HARNESS_SOURCE),
        _md("## Controls and checks\n\n| arm | readable runs | hits | median effect | "
            f"median p |\n|---|---|---|---|---|\n{tally_rows}\n\n| run | seed offset | status | "
            f"effect | p | n | successes |\n|---|---|---|---|---|---|---|\n{run_rows}\n\n"
            f"{checks}"),
        _md(f"## Analysis\n\n**Verdict: {state.verdict}**\n\n"
            + (f"Why it can't be reported as a result:\n{reasons}\n\n" if reasons else "")
            + f"{state.findings}\n\n" + "\n".join(f"- {c}" for c in state.caveats)),
        _md(f"## Reflection\n\n**What worked.** {state.what_worked}\n\n"
            f"**What failed.** {state.what_failed}\n\n**Strategy change.** "
            f"{state.change_summary}\n\n### Lessons before\n{lessons_before}\n\n"
            f"### Lessons after\n{lessons_after}"),
        _md(f"## Human decisions\n\n{decision_lines}"),
        _md("## Provenance\n\n" + "\n".join(prov_rows)),
    ]
    return {"cells": cells, "metadata": {"kernelspec": {
        "display_name": "Python 3", "language": "python", "name": "python3"},
        "palissy": {"project_id": project_id}}, "nbformat": 4, "nbformat_minor": 5}


def write_notebook(nb: dict, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(nb, indent=1), encoding="utf-8")
    return path
