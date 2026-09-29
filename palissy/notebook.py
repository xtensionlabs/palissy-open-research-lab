"""Reproducible .ipynb output. Written as plain nbformat-4 JSON (no nbformat dependency).

The code cell holds the exact script that ran; its recorded output is stored alongside, and the
provenance table at the end links every claim back to a record id.
"""

import json
from pathlib import Path


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

    cells = [
        _md(f"# {question}\n\nPalissy project `{project_id}` · total model spend "
            f"**${total_cost:.4f}**\n\nGenerated with Nebius Token Factory (Nemotron 3) and Tavily."),
        _md(f"## Literature\n\n{state.literature_summary}\n\n{sources}"),
        _md(f"## Hypothesis\n\n{state.hypothesis}\n\n**Prediction.** {state.prediction}\n\n"
            f"**Rationale.** {state.rationale}"),
        _md("## Experiment\n\nExecuted in: `" + state.backend + "`. Requires `numpy`."),
        _code(state.code, state.stdout, state.stderr),
        _md(f"## Analysis\n\n**Verdict: {state.verdict}**\n\n{state.findings}\n\n"
            + "\n".join(f"- {c}" for c in state.caveats)),
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
