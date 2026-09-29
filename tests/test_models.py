import pytest

from palissy.models import Flavor, ModelResolutionError, estimate_cost, resolve_ids

LIVE = [
    "moonshotai/Kimi-K3",
    "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
    "nvidia/Nemotron-3_5-Lightning",
    "nvidia/Nemotron-3-Ultra-550b-a55b",
    "nvidia/nemotron-3-super-120b-a12b",
]


def test_resolve_ids_from_live_list():
    ids = resolve_ids(LIVE)
    assert ids[Flavor.NANO].lower().endswith("nano-30b-a3b")
    assert ids[Flavor.SUPER].lower().endswith("super-120b-a12b")
    assert ids[Flavor.ULTRA].lower().endswith("ultra-550b-a55b")


def test_resolve_ids_ignores_fast_variants():
    ids = resolve_ids(LIVE + ["nvidia/nemotron-3-super-120b-a12b-fast"])
    assert not ids[Flavor.SUPER].endswith("-fast")


def test_resolve_ids_fails_loudly_when_missing():
    with pytest.raises(ModelResolutionError):
        resolve_ids([m for m in LIVE if "Ultra" not in m])


def test_estimate_cost():
    assert estimate_cost(Flavor.ULTRA, 1_000_000, 1_000_000) == pytest.approx(2.70)
    assert estimate_cost(Flavor.NANO, 1000, 1000) == pytest.approx(0.00025)
