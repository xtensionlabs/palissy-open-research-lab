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

- 2026-09-30, reasoning models and token budgets: Ultra (and Super) return their thinking in a separate
  `reasoning_content` field, and it counts against `max_tokens`. With `max_tokens=4000`, Ultra as critic and
  as reflector spent the whole budget thinking and stopped mid-JSON, which crashed two live runs. Budgets
  of 6000-8000 plus one "reply again, shorter" retry fixed it. A per-request switch such as
  `chat_template_kwargs: {enable_thinking: false}` does work on Ultra (7 tokens vs 93 on a trivial
  prompt), but it isn't documented in the Token Factory API reference I found. Worth documenting.
- Ultra as design critic, given a fixed-seed simulation, first objected that a fixed seed "makes the
  outcome predictable". That is wrong (reproducibility requires it), and it only stopped after the prompt
  said so. Super's first-pass critic was more useful than expected; Ultra's second look mostly agreed.
- Super wrote nested JSON for fields asked for as strings (`positive_control: {effect_planted, size}`),
  so the contract parser flattens dicts to text rather than rejecting them.
- A transient `APIConnectionError` killed one run mid-design. The `openai` SDK retries twice by default;
  raised to 6.

- 2026-10-01, Super and Ultra as reviewers, in context: I added a critic question, "is the treatment
  effect typed in rather than produced by the model?", after a run whose script hard-coded the
  treatment mean (`comp_loc = 0.78`). I have only seen it pass so far (Super returned ok for an
  inhibition-model design, run 86fe37ec); I have not yet seen it catch a typed-in design live.
  Super's analyst misread a number in an earlier run ("well under 200%" for a 320% effect), so figures
  in its prose are now checked against the run output in code and flagged, not trusted. Super also
  wrote a positive control as `baseline - 0.5`, a noiseless shift that any test detects; the controls
  are only as informative as the prompt makes them.

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
- 2026-09-30 spike (branching and replay, about $0 and 30 minutes):
  - Several `contree run --use <image-uuid> -D` processes, each with its own `-S` session key, run fine in
    parallel from one checkpoint image: 3 concurrent runs took 4.8s wall, the same as one. That is the
    right primitive for fanning out experiment arms, and it doesn't depend on `session checkout`, which
    mutates a single local pointer and isn't safe to share between concurrent callers.
  - Replay is exact: a fresh session from the base tag with the script attached again, and a disposable
    run from the saved checkpoint image, both reproduced the seeded output byte for byte.
  - `session show` / `session` with `-o json` gave me `current_image` (a UUID) directly, which is what
    makes "run from this checkpoint" scriptable. That's a good, underdocumented affordance.
  - `session delete -y` accepts several keys at once, which made cleanup easy.
- 2026-10-01, parallel branches and replay in the real pipeline (project 86fe37ec, 15 branches):
  - `-o json run` returns the operation `uuid`, `status`, `duration`, `exit_code`, stdout/stderr and
    `metadata.result.state.timed_out`. That last field replaces my exit-127 / wrapped -1 timeout
    guesswork from 09-30, and the uuid gives provenance a real sandbox operation id. I did not find
    CPU, memory or IO metrics in the CLI's JSON, which the product page led me to expect.
  - Forking 15 throwaway branches (`run --use <checkpoint-uuid> -D`, one `-S` session key each) at
    3 in flight took about 33 s end to end, roughly 4.5 s per branch including VM start. Nothing
    leaked: branch sessions are removed with `session delete -f k1 k2 ...` and the session count
    went back to what it was.
  - Replaying all 15 from the clean base image (files re-attached with `-F` on every run) took 50 s,
    about 40% slower per branch than forking from the snapshot, so the checkpoint does save real time.
    All 15 outputs matched byte for byte, including seeds shifted by a harness (offset 1009 gave the
    same draw locally and in the sandbox).
  - The concurrency ceiling I hit was my laptop, not ConTree: each branch is a `contree` CLI process
    (a Python exe), and with under 1 GB of RAM free I held it to 3 to 4 at once. The Beta limit of 50
    operations was never close. A thin HTTP client in the docs would let a service fan out without
    one OS process per operation.
  - A run that fails after the command starts and one that never started are distinguishable only by
    whether the JSON has an `exit_code`; I treat "no JSON" as an infrastructure failure and let the
    fallback executor decide, which kept a transient CLI error from being scored as a failed experiment.
