"""Executor layer: the seed harness, local branches, and ConTree branching with a faked CLI."""

import asyncio
import json

import pytest

from palissy.sandbox import ContreeError, ContreeExecutor, Job, LocalExecutor, SEED_STRIDE
from palissy.sandbox.base import gather_limited

SEEDED = '''import random, sys
random.seed(7)
print("RESULT_JSON:", sys.argv[1:], round(random.random(), 6))
'''
UNSEEDED = "import random\nprint(round(random.random(), 6))\n"


def test_replicate_k_shifts_seeds_by_a_fixed_stride():
    assert Job("treatment", 0).seed_offset == 0
    assert Job("positive", 3).seed_offset == 3 * SEED_STRIDE
    assert Job("negative", 1).label == "negative#2"


async def test_offset_zero_is_the_script_run_directly_and_other_offsets_differ():
    ex = LocalExecutor()
    direct = await ex.run(SEEDED, args=["negative"])
    ck = await ex.checkpoint(SEEDED)
    a, b, again = await ex.run_branches(
        ck, [Job("negative", 0), Job("negative", 1), Job("negative", 1)], concurrency=2)
    assert a.result.stdout == direct.stdout  # the harness is invisible at offset 0
    assert b.result.stdout != a.result.stdout  # a different seed, so a different draw
    assert b.result.stdout == again.result.stdout  # but the same one every time


async def test_a_script_that_never_seeds_still_replays_exactly():
    ex = LocalExecutor()
    ck = await ex.checkpoint(UNSEEDED)
    one, two, other = await ex.run_branches(
        ck, [Job("treatment", 2), Job("treatment", 2), Job("treatment", 3)])
    assert one.result.stdout == two.result.stdout != other.result.stdout


async def test_numpy_seeds_are_shifted_too():
    pytest.importorskip("numpy")
    code = ("import numpy as np\nnp.random.seed(5)\nprint(np.random.rand())\n"
            "print(np.random.default_rng(5).random())\nprint(np.random.RandomState(5).rand())\n")
    ex = LocalExecutor()
    ck = await ex.checkpoint(code)
    zero, one = await ex.run_branches(ck, [Job("treatment", 0), Job("treatment", 1)])
    direct = await ex.run(code)
    assert zero.result.stdout == direct.stdout
    assert one.result.stdout != zero.result.stdout
    shifted, original = one.result.stdout.split(), zero.result.stdout.split()
    # seed() and RandomState() share a generator, so they agree with each other, and every
    # one of the three differs from its unshifted value
    assert shifted[0] == shifted[2] and all(s != o for s, o in zip(shifted, original))


async def test_a_failing_or_slow_branch_is_captured_not_raised():
    ex = LocalExecutor()
    ck = await ex.checkpoint("import sys, time\narm = sys.argv[1]\n"
                             "if arm == 'positive': raise SystemExit(3)\n"
                             "if arm == 'negative': time.sleep(5)\nprint('ok')\n")
    t, p, n = await ex.run_branches(ck, [Job("treatment", 0), Job("positive", 0),
                                         Job("negative", 0)], timeout=1)
    assert t.result.ok and t.result.stdout.strip() == "ok"
    assert p.result.exit_code == 3 and n.result.exit_code == 124


async def test_gather_limited_caps_concurrency_and_keeps_order():
    live = peak = 0

    async def work(i):
        nonlocal live, peak
        live += 1
        peak = max(peak, live)
        await asyncio.sleep(0.01)
        live -= 1
        return i
    assert await gather_limited((work(i) for i in range(10)), 3) == list(range(10))
    assert peak == 3


# --- ConTree, with the CLI faked ---------------------------------------------------------


def op(stdout="", exit_code=0, timed_out=False, uuid="01a0f611"):
    return json.dumps({"uuid": uuid, "status": "SUCCESS", "exit_code": exit_code,
                       "stdout": stdout, "stderr": "", "error": "",
                       "metadata": {"result": {"state": {"exit_code": exit_code,
                                                         "timed_out": timed_out}}}})


class FakeCli:
    """Stands in for the contree CLI: records calls, answers `-o json` runs."""

    def __init__(self, *, fail_arm=None, no_json_arm=None):
        self.calls, self.fail_arm, self.no_json_arm = [], fail_arm, no_json_arm

    async def __call__(self, *args, timeout=300, cwd=None, session=None):
        self.calls.append({"args": args, "session": session, "cwd": cwd})
        if args[:3] == ("-o", "json", "session"):
            return 0, json.dumps({"current_image": "img-1"}), ""
        if args[:2] == ("-o", "json") and "run" in args:
            arm = args[-1]
            if arm == self.no_json_arm:
                return 1, "", "HTTP 503"
            if arm == self.fail_arm:
                return 0, op("", exit_code=2), ""
            offset = next(a for a in args if a.startswith("PALISSY_SEED_OFFSET="))
            return 0, op(f"{arm} {offset.split('=')[1]}\n"), ""
        return 0, "", ""

    def runs(self):
        return [c for c in self.calls if "run" in c["args"] and "-D" in c["args"]]

    def deleted(self):
        return [c["args"][3:] for c in self.calls if c["args"][:3] == ("session", "delete", "-f")]


def contree(cli):
    ex = ContreeExecutor("s")
    ex._cli, ex._ready = cli, True
    return ex


async def test_checkpoint_attaches_script_and_harness_once_and_reads_the_image():
    cli = FakeCli()
    ck = await contree(cli).checkpoint("print(1)")
    assert ck.image == "img-1" and ck.base == "tag:palissy/base/python:3.12-numpy"
    first = cli.calls[0]["args"]
    assert first[0] == "run" and "experiment.py:/work/experiment.py" in first
    assert "harness.py:/work/harness.py" in first and first[-1] == "true"


async def test_branches_fork_from_the_checkpoint_each_in_its_own_session():
    cli = FakeCli()
    ex = contree(cli)
    ck = await ex.checkpoint("print(1)")
    jobs = [Job("treatment", 0), Job("positive", 0), Job("negative", 1)]
    out = await ex.run_branches(ck, jobs, concurrency=2)
    assert [b.result.stdout.strip() for b in out] == ["treatment 0", "positive 0",
                                                      "negative 1009"]
    runs = cli.runs()
    assert len({c["session"] for c in runs}) == 3 and "s" not in {c["session"] for c in runs}
    for c, j in zip(runs, jobs):
        a = c["args"]
        assert a[a.index("--use") + 1] == "img-1" and "-D" in a
        assert f"PALISSY_SEED_OFFSET={j.seed_offset}" in a
        assert a[-5:] == ("--", "python", "/work/harness.py", "/work/experiment.py", j.arm)
        assert "-F" not in a  # the snapshot already has the files
    assert out[0].result.op_id == "01a0f611"
    # the throwaway branch sessions are deleted afterwards
    assert sorted(cli.deleted()[0]) == sorted(c["session"] for c in runs)


async def test_clean_branches_start_from_the_base_image_and_attach_the_files():
    cli = FakeCli()
    ex = contree(cli)
    ck = await ex.clean_checkpoint("print(1)")
    assert ck.image == ""
    await ex.run_branches(ck, [Job("treatment", 2)], clean=True)
    (c,) = cli.runs()
    a = c["args"]
    assert a[a.index("--use") + 1] == "tag:palissy/base/python:3.12-numpy"
    assert "experiment.py:/work/experiment.py" in a and "harness.py:/work/harness.py" in a
    assert "PALISSY_SEED_OFFSET=2018" in a and c["cwd"]


async def test_a_command_that_exits_nonzero_is_a_result_not_an_error():
    cli = FakeCli(fail_arm="positive")
    ex = contree(cli)
    ck = await ex.checkpoint("x")
    out = await ex.run_branches(ck, [Job("treatment", 0), Job("positive", 0)])
    assert [b.result.exit_code for b in out] == [0, 2]


async def test_an_infrastructure_failure_raises_after_one_retry_and_still_cleans_up():
    cli = FakeCli(no_json_arm="negative")
    ex = contree(cli)
    ck = await ex.checkpoint("x")
    with pytest.raises(ContreeError, match="no result from contree"):
        await ex.run_branches(ck, [Job("treatment", 0), Job("negative", 0)])
    negative = [c for c in cli.runs() if c["args"][-1] == "negative"]
    assert len(negative) == 2  # tried twice
    assert len(cli.deleted()) == 1 and len(cli.deleted()[0]) == 2  # nothing left behind


def test_timeouts_and_missing_exit_codes_are_read_from_the_operation():
    ex = ContreeExecutor("s")
    done = ex._result(0, op("hi\n"), "", 1.5, 120)
    assert done.ok and done.stdout == "hi\n" and done.op_id == "01a0f611" and done.duration_s == 1.5
    slow = ex._result(0, op("", exit_code=127, timed_out=True), "", 120.2, 120)
    assert slow.exit_code == 124 and "timeout after 120s" in slow.stderr
    nocode = ex._result(0, json.dumps({"uuid": "u", "exit_code": None, "error": "OOM"}), "", 1, 120)
    assert nocode.exit_code == 1 and nocode.stderr == "OOM"
    with pytest.raises(ContreeError):
        ex._result(1, "", "boom", 1, 120)
    with pytest.raises(ContreeError):
        ex._result(0, "not json", "", 1, 120)


async def test_close_deletes_the_executors_own_session_once():
    cli = FakeCli()
    ex = contree(cli)
    await ex.close()
    await ex.close()
    assert cli.deleted() == [("s",)]
