"""The mechanical verdict: a result is reported only if the test could have come out the other way."""

import pytest

from palissy.stages.critic import _parse
from palissy.stages.hypothesis import _json_block, phrasing_problem
from palissy.stages.common import extract_code
from palissy.stages.verdict import Contract, decide, detected, parse_result

from .test_pipeline import CONTRACT


def arm(effect, p, n=200, successes=None, exit_code=0):
    return {"exit_code": exit_code, "result": {"effect": effect, "p_value": p, "n": n,
                                               "successes": successes}}


C = Contract.parse(CONTRACT)
CLEAN = dict(positive=arm(0.5, 0.001), negative=arm(0.01, 0.7))


def test_clean_run_supports_or_refutes_by_rule():
    assert decide(C, {"treatment": arm(0.3, 0.01), **CLEAN}).verdict == "supports"
    assert decide(C, {"treatment": arm(0.05, 0.4), **CLEAN}).verdict == "refutes"
    # significant, but in the opposite direction to the pre-registered one
    assert decide(C, {"treatment": arm(-0.3, 0.01), **CLEAN}).verdict == "refutes"


def test_missed_positive_control_is_inconclusive():
    v = decide(C, {"treatment": arm(0.0, 0.5), "positive": arm(0.1, 0.3),
                   "negative": arm(0.01, 0.7)})
    assert v.verdict == "inconclusive" and "planted on purpose" in v.reasons[0]


def test_negative_control_that_fires_is_inconclusive():
    v = decide(C, {"treatment": arm(0.3, 0.01), "positive": arm(0.5, 0.001),
                   "negative": arm(0.2, 0.01)})
    assert v.verdict == "inconclusive" and "where none exists" in v.reasons[0]


def test_p_pinned_at_one_is_inconclusive():
    v = decide(C, {"treatment": arm(0.0, 1.0), **CLEAN})
    assert v.verdict == "inconclusive" and any("p = 1" in r for r in v.reasons)


def test_all_or_nothing_counts_are_fixed_by_parameters():
    v = decide(C, {"treatment": arm(0.0, 0.5, 2000, 0), "positive": arm(0.5, 0.001, 2000, 2000),
                   "negative": arm(0.0, 0.6, 2000, 0)})
    assert v.verdict == "inconclusive" and any("fixed by the parameters" in r for r in v.reasons)
    # one arm with a real count is enough: the outcome wasn't fixed
    ok = decide(C, {"treatment": arm(0.1, 0.5, 2000, 37), "positive": arm(0.5, 0.001, 2000, 2000),
                    "negative": arm(0.0, 0.6, 2000, 0)})
    assert ok.verdict == "refutes"


def test_treatment_identical_to_negative_control():
    v = decide(C, {"treatment": arm(0.01, 0.7), **CLEAN})
    assert v.verdict == "inconclusive" and "negative control's number" in v.reasons[0]


def test_crash_is_failed_and_missing_arm_is_failed():
    assert decide(C, {"treatment": arm(0, 0, exit_code=1)}).verdict == "failed"
    assert decide(C, {"treatment": arm(0.3, 0.01), "positive": arm(0.5, 0.001)}).verdict == "failed"


def test_no_contract_or_unreadable_output_is_inconclusive():
    assert decide(None, {"treatment": arm(0.3, 0.01), **CLEAN}).verdict == "inconclusive"
    bad = {"treatment": {"exit_code": 0, "result": None}, **CLEAN}
    v = decide(C, bad)
    assert v.verdict == "inconclusive" and "no RESULT_JSON" in v.reasons[0]
    v = decide(C, {"treatment": arm(0.3, 1.7), **CLEAN})
    assert v.verdict == "inconclusive"


def test_contract_parse_names_what_is_missing():
    with pytest.raises(ValueError, match="positive_control.*direction"):
        Contract.parse({**CONTRACT, "positive_control": "", "direction": "sideways"})
    with pytest.raises(ValueError, match="alpha"):
        Contract.parse({**CONTRACT, "alpha": 0.9})


def test_a_named_size_must_be_reached_to_support():
    """Hulk run 2: hypothesis said >8-fold, contract only tested direction, result was ~6-fold."""
    c = Contract.parse({**CONTRACT, "min_effect": 7})
    run = {"treatment": arm(5.96, 0.001), "positive": arm(38.4, 0.001), "negative": arm(0.007, 0.36)}
    v = decide(c, run)
    assert v.verdict == "refutes" and any(ch.name == "Effect size" and not ch.passed for ch in v.checks)
    assert decide(Contract.parse({**CONTRACT, "min_effect": 5}), run).verdict == "supports"
    assert decide(C, run).verdict == "supports"  # no size named: direction is the claim
    assert C.min_effect == 0
    with pytest.raises(ValueError, match="min_effect"):
        Contract.parse({**CONTRACT, "min_effect": -1})


def test_nested_contract_fields_are_flattened_to_words():
    c = Contract.parse({**CONTRACT, "positive_control": {"effect_planted": "a = 2.0",
                                                         "size": "ratio > 100"}})
    assert c.positive_control == "a = 2.0; ratio > 100"


def test_fingerprint_changes_with_contract_or_hypothesis():
    h = "Loss of myostatin increases muscle mass"
    assert C.fingerprint(h) == Contract.parse(CONTRACT).fingerprint(h)
    assert C.fingerprint(h) != Contract.parse({**CONTRACT, "alpha": 0.01}).fingerprint(h)
    assert C.fingerprint(h) != C.fingerprint(h + " a lot")


def test_direction_any_counts_either_sign():
    c = Contract.parse({**CONTRACT, "direction": "any"})
    assert detected({"effect": -0.4, "p_value": 0.01}, c)
    assert not detected({"effect": -0.4, "p_value": 0.2}, c)


def test_parse_result_takes_the_last_valid_line():
    out = 'x\nRESULT_JSON: {"effect": 1, "p_value": 0.5, "n": 3}\nRESULT_JSON: {"effect": 2, "p_value": 0.1, "n": 3}\n'
    assert parse_result(out)["effect"] == 2
    assert parse_result("RESULT: supports") is None
    assert parse_result("RESULT_JSON: {not json}") is None


def test_unfalsifiable_phrasings_are_caught():
    assert phrasing_problem("Humans cannot express Hulk-like traits")
    assert phrasing_problem("X", "There is no evidence that Y")
    assert phrasing_problem("Gamma exposure is impossible to survive")
    assert not phrasing_problem("Myostatin knockout increases muscle mass by over 20%")


def test_design_reply_splits_into_contract_and_code():
    reply = ('Plan:\n```json\n{"alpha": 0.05}\n```\n\nThen:\n```python\nimport sys\nprint(1)\n```')
    assert _json_block(reply) == {"alpha": 0.05}
    assert extract_code(reply) == "import sys\nprint(1)"
    assert extract_code("```\nprint(2)\n```") == "print(2)"


def test_critic_ok_with_a_failed_question_is_a_concern():
    level, answers, _ = _parse('{"level": "ok", "answers": {"knowable_in_advance": '
                               '{"ok": false, "why": "0.001*1e5=100 << 1e6"}}, "summary": "s"}')
    assert level == "concern" and not answers["knowable_in_advance"]["ok"]
    assert answers["null_is_real"]["why"] == "No answer given."
    assert _parse('{"level": "weird"}')[0] == "concern"
