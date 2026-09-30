# Palissy

Open research laboratory for biology. An AI research collaborator, not a black-box AI scientist.

Built for the Nebius x NVIDIA Global AI Hackathon (Best Apps and Agents track).

Pipeline: literature (Tavily) → hypothesis → experiment design → execution (ConTree sandboxes)
→ analysis → reflection → reproducible notebook. The human approves, rejects, modifies, or
injects at each decision point.

## Status

Working end to end: question, literature, hypothesis, experiment, sandbox run, analysis, reflection, notebook, with a human decision at three gates and a full provenance trail. `CLAUDE.md` holds the spec and build plan.

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

Open the app, ask a question, and decide at each gate. `palissy "your question" --executor local` runs the same pipeline in a terminal.

Set `PALISSY_ALLOW_LOCAL_FALLBACK=1` to let the API fall back to a non-isolated local run if ConTree is down. It is off by default because it executes model-written code on the server.

## Tests

```bash
pytest                          # backend
cd frontend && npm run lint && npm run build
```

`frontend/scripts/layout-audit.js` is a console script that reports overlapping or clipped text on any page.

## How Palissy uses Nebius / NVIDIA / Tavily

_To be filled in as integrations land._

## License

Apache-2.0. See `LICENSE`.
