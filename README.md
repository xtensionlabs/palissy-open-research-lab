# Palissy

Open research laboratory for biology. An AI research collaborator, not a black-box AI scientist.

Built for the Nebius x NVIDIA Global AI Hackathon (Best Apps and Agents track).

Pipeline: literature (Tavily) → hypothesis → experiment design → execution (ConTree sandboxes)
→ analysis → reflection → reproducible notebook. The human approves, rejects, modifies, or
injects at each decision point.

## Status

Scaffold only. See `CLAUDE.md` for the spec and build plan.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -e ".[dev]"
cp .env.example .env            # fill in NEBIUS_API_KEY, NEBIUS_AI_PROJECT, TAVILY_API_KEY
```

## How Palissy uses Nebius / NVIDIA / Tavily

_To be filled in as integrations land._

## License

Apache-2.0. See `LICENSE`.
