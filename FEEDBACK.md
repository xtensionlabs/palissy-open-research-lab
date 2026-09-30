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
- Instruction-following limits: told "under 30 seconds", Super wrote a simulation (200k generations x
  2000 loci) that timed out at 60s. Tightening the prompt plus one bounded repair pass fixed it.
- Ultra as analyst overstated a result: the script printed `RESULT: inconclusive` with all-zero output,
  yet the analysis said "refutes". Palissy now caps the verdict at the script's own RESULT line.
- Ultra as reflector recommended 10^5-10^6 generations, contradicting the runtime budget until the
  budget was added to its prompt. Reflection needs the same hard constraints as design.
- Full pipeline cycle with Ultra + Super + Nano (7 stages, 3 human gates): $0.0111.

## Base vs Fast flavors

## ConTree Sandboxes (fork / rollback under load)

- 2026-09-29: Blocked at onboarding. `contree auth` succeeded and `whoami` returned 200, but the profile
  showed status `inactive` and `images` / `use` returned `HTTP 403: Insufficient permissions: list and
  spawn`, while the same API key and project worked for inference. Emailed contree@nebius.com.
  Nothing in the CLI or docs said Sandboxes needed a separate activation; `whoami` succeeding while
  every other call 403'd made it look like a client bug. A clearer error ("Sandboxes not enabled for
  this project") would have saved a day.
- 2026-09-30: Nebius confirmed activation; profile status flipped to `ok` with no re-auth needed.
- Round trip verified by hand, then through `palissy/sandbox/contree.py`: run -> checkpoint ->
  `session branch` + `checkout` -> write a file on the branch -> `checkout main` -> file is gone.
  Fork/rollback is real filesystem isolation and cheap (a run takes ~5s including VM start).
- Things that differed from what I expected (each cost a failed call):
  - `contree file put` does not exist; files go in with `run -F host:/instance/path` or `file cp`.
  - `cd /work` fails on a fresh image; attaching a file creates the directory.
  - `python:3.12` has no numpy. Building a base image once (`pip install`, then `tag`) and reusing
    the tag is the right pattern; `contree images --prefix=` made the existence check easy.
  - A timed-out `run` exits 127 on Linux but came back as 4294967295 (unsigned -1) on Windows, so a
    timeout is indistinguishable from "command not found" without checking wall time.
  - On Windows the `host_path:instance_path` syntax collides with drive letters (`C:\...`); using a
    relative host path with cwd set avoids it. Git Bash also rewrites `/work` to
    `C:/Program Files/Git/work` unless `MSYS_NO_PATHCONV=1`.
  - `-L error` is needed to keep CLI log lines out of stderr; exit codes propagate correctly.
- Good: `contree agent` manual, the session/branch model, and per-run history (`session show`) map
  directly onto an experiment-branching loop. Each run is a checkpoint, so every result is replayable.
- Sessions accumulate (`agent_palissy_*`); I have not yet cleaned up with `session delete`.
