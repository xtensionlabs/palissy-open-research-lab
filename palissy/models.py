"""Single home for model resolution, routing policy, and call logging (CLAUDE.md §2.2, §4).

TODO (Milestone 1):
  - resolve Nano/Super/Ultra IDs live from GET /v1/models, cache, fail loudly if missing
  - expose routing as a policy: stage -> flavor (Ultra: hypothesis/reflection,
    Super: codegen/orchestration, Nano: summarize/extract)
  - log every call: model, tokens in/out, cost, latency, into the provenance store
"""

from enum import Enum


class Flavor(str, Enum):
    NANO = "nano"
    SUPER = "super"
    ULTRA = "ultra"


# Routing policy: one place, not scattered ifs.
STAGE_POLICY: dict[str, Flavor] = {
    "literature_summary": Flavor.NANO,
    "hypothesis": Flavor.ULTRA,
    "experiment_design": Flavor.SUPER,
    "code_generation": Flavor.SUPER,
    "analysis": Flavor.SUPER,
    "reflection": Flavor.ULTRA,
    "notebook": Flavor.NANO,
}
