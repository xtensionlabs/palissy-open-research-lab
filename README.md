# Palissy

Open research laboratory for biology. An AI research collaborator, not a black-box AI scientist.

Built for the Nebius x NVIDIA Global AI Hackathon (Best Apps and Agents track).

Pipeline: literature (Tavily) → hypothesis → experiment design → execution (ConTree sandboxes)
→ analysis → reflection → reproducible notebook. The human approves, rejects, modifies, or
injects at each decision point.

## Status

Working end to end: question check, literature, hypothesis, pre-registered experiment, sandbox runs, analysis, reflection, notebook, with a human decision at each gate and a full provenance trail.

What makes a result mean something:

- **The test is committed before it runs.** The design pre-registers the statistic, null, threshold, direction, minimum effect, and a positive and a negative control. The hash is frozen when you approve it.
- **The verdict is computed by rule, not asked of a model.** Every arm runs under several seeds as separate ConTree branches forked from one checkpoint. A result is only reported as supports or refutes if the positive control is detected, the negative control's false alarms are no more frequent than alpha allows, the numbers aren't fixed by the parameters, and the treatment gives the same answer across seeds. Otherwise it is `inconclusive`, with the reason.
- **A design critic reads the experiment before you do.** It asks whether the outcome is knowable in advance, whether the null is a real null, whether the treatment effect is typed in rather than produced by the model, and whether the test does what it says. It escalates to Ultra only when Super objects.
- **Questions that can't be tested are said so.** Fiction and untestable questions stop at a gate, with the closest testable reframing; you can continue knowingly.
- **Any run can be replayed.** The Replay button (or `palissy --replay <project id>`) starts every recorded run again from the clean base image with the stored script and seeds, and compares the output byte for byte.

Limits worth knowing: experiments are small numpy simulations, labelled as simulated data. A simulation's answer follows from its own assumptions, so a "supports" says the model behaves that way, not that biology does. `CLAUDE.md` holds the spec and build plan.

## Setup

Requires Python 3.11+, Node 20+, a Nebius Token Factory key with Sandboxes enabled, and a Tavily key.

```bash
python -m venv .venv
.venv/Scripts/activate       # Windows (Git Bash); on macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env            # fill in NEBIUS_API_KEY, NEBIUS_AI_PROJECT, TAVILY_API_KEY
contree auth                    # once; reads the keys above

cd frontend
npm install
cp .env.local.example .env.local
```

## Run

```bash
palissy-serve                   # API on http://localhost:8000
cd frontend && npm run dev      # app on http://localhost:3000
```

Open the app, ask a question, and decide at each gate. `palissy "your question" --executor local` runs the same pipeline in a terminal, and `palissy --replay <project id>` re-runs a finished project's runs in clean sandboxes.

| Variable | Default | What it does |
|---|---|---|
| `PALISSY_REPLICATES` | 5 | Seeds per arm. 3 arms x 5 seeds = 15 sandbox branches per experiment |
| `PALISSY_MAX_PARALLEL` | 4 | Branches in flight at once. ConTree Beta allows 50 simultaneous operations; each branch is a `contree` CLI process, so lower this on a small machine |
| `PALISSY_EXECUTOR` | `contree` | `contree` or `local` |
| `PALISSY_ALLOW_LOCAL_FALLBACK` | off | Fall back to a non-isolated local run if ConTree errors |

Set `PALISSY_ALLOW_LOCAL_FALLBACK=1` to let the API fall back to a non-isolated local run if ConTree is down. It is off by default because it executes model-written code on the server.

## Tests

```bash
pytest                          # backend
cd frontend && npm run lint && npm run build
```

`frontend/scripts/layout-audit.js` is a console script that reports overlapping or clipped text on any page.

## How Palissy uses Nebius / NVIDIA / Tavily

**Nebius Token Factory** serves every model call through the OpenAI-compatible API. Model IDs are resolved live from `GET /v1/models` (`palissy/models.py`), never hard-coded, and every call is logged with model, tokens, cost and latency.

**Nemotron 3** is routed by stage, in one policy table:

| Stage | Model | Why |
|---|---|---|
| Question triage, literature summary | Nano | Short, light calls |
| Hypothesis, reflection | Ultra | The hardest reasoning, and reflection rewrites the strategy for every later run |
| Experiment design, design critic, analysis, code repair | Super | Dependable code and structured review |
| Critic's second look | Ultra | Only when Super's critic objects, so deep reasoning is spent where a reviewer asks for it |

The Cost chapter shows the real logged spend per stage and what the same step would have cost on each tier.

**ConTree sandboxes** run all experiment code, never the host. An experiment snapshots the sandbox once with the script attached, then forks every (arm, seed) run from that checkpoint as a throwaway branch, up to `PALISSY_MAX_PARALLEL` at a time. A branch that fails is rolled back and left out of the verdict. Replay forks again from the clean base image instead, to show the result doesn't depend on leftover state. See `palissy/sandbox/contree.py`.

**Tavily** does the literature search. Its results are cited in the hypothesis and linked into the provenance chain.

Where Token Factory sped the build up: a $0.01 to $0.03 full pipeline run (7 to 10 model calls and 15 sandbox branches) made it cheap to run the real system against the real question after every change, rather than trusting stubs. `FEEDBACK.md` has the running notes.

## License

Apache-2.0. See `LICENSE`.
