# Feedback log (Nebius Token Factory / AI Cloud / NVIDIA models)

Running notes for the mandatory hackathon feedback section. Write each entry the day it happens.
Be specific: name the exact tool or model.

## Template

- **Date:**
- **Product / model:**
- **Used for:**
- **What worked:**
- **What needed work:**
- **Would I build with it again, and why:**

## Onboarding (zero to hello world)

- 2026-09-29: Account activated, $25 promo credits redeemed in Token Factory; a further $25 pending approval.

## Token Factory: `/v1/models` discovery

- 2026-09-29: `GET /v1/models` works with the standard `openai` SDK (`base_url=.../v1/`). Returns
  25 models with only `id`, `created`, `owned_by`, `shutdown_date`: no pricing, context length or
  capability metadata, so cost tracking needs a hand-maintained price table copied from the console.
- Nemotron IDs are inconsistent in casing/separators (`nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`,
  `nvidia/nemotron-3-super-120b-a12b`, `nvidia/Nemotron-3-Ultra-550b-a55b`), which justified resolving
  by pattern at runtime. An extra `nvidia/Nemotron-3_5-Lightning` is also listed.
- `shutdown_date` in the response is useful for detecting deprecations; Palissy does not use it yet.

## Nemotron 3 Nano / Super / Ultra

- 2026-09-29 first full cycle (question -> Tavily -> Ultra hypothesis -> Super experiment code):
  Ultra 1185 in / 1235 out, 5.4s, $0.0033; Super 270 in / 3164 out, 16.3s, $0.0013;
  Nano summary 236 in / 203 out, 8.8s. Whole cycle $0.0046, so a $25 credit is not a constraint for dev.
- Ultra returned parseable JSON when told "JSON only", but Palissy still extracts the outermost
  `{...}` defensively. Super followed the "single ```python block, end with RESULT:" instruction.
- Nano's output began with a blank line; stripped in the wrapper.

## Base vs Fast flavors

## ConTree Sandboxes (fork / rollback under load)

- 2026-09-29: Blocked at onboarding. `contree auth` succeeds and `whoami` returns 200, but the profile
  shows status `inactive` and `images` / `use` return `HTTP 403: Insufficient permissions: list and
  spawn`. Same API key and project as inference, which works. Emailed contree@nebius.com; awaiting reply.
- The CLI reads `NEBIUS_API_KEY` / `NEBIUS_AI_PROJECT` for `contree auth`, and `contree agent` prints a
  clear agent manual. Both were good onboarding touches.
- Not yet known: the exact CLI/SDK commands behind fork/rollback in practice. `palissy/sandbox/contree.py`
  is written from the manual and untested.
