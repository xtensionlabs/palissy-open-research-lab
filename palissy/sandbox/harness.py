"""Palissy harness: runs a model-written experiment with a replicate seed offset.

Shipped into the sandbox next to the experiment and run as

    PALISSY_SEED_OFFSET=<k> python harness.py experiment.py <arm>

Every integer seed the script passes to `random` or `numpy.random` is shifted by the offset, so
replicate k of a fixed-seed script is a different but fully reproducible draw. Offset 0 changes
nothing: the script behaves exactly as if run directly. Scripts that never seed are seeded from
the offset, so even they replay exactly.
"""

import os
import random
import runpy
import sys

OFFSET = int(os.environ.get("PALISSY_SEED_OFFSET", "0"))


def _shift(seed):
    if isinstance(seed, int) and not isinstance(seed, bool):
        return seed + OFFSET
    return seed


def _install() -> None:
    random.seed(OFFSET)
    _random_seed = random.seed
    random.seed = lambda a=None, *args, **kw: _random_seed(_shift(a), *args, **kw)
    try:
        import numpy as np
    except ImportError:
        return
    np.random.seed(OFFSET)
    _np_seed, _default_rng = np.random.seed, np.random.default_rng
    np.random.seed = lambda seed=None: _np_seed(_shift(seed))
    np.random.default_rng = lambda seed=None: _default_rng(
        _shift(seed) if seed is not None else OFFSET)

    class RandomState(np.random.RandomState):
        def __init__(self, seed=None):
            super().__init__(_shift(seed) if seed is not None else OFFSET)

    np.random.RandomState = RandomState


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("usage: harness.py experiment.py [args...]")
    script = sys.argv[1]
    sys.argv = sys.argv[1:]  # the script sees itself as argv[0] and its own arguments after
    _install()
    runpy.run_path(script, run_name="__main__")


if __name__ == "__main__":
    main()
