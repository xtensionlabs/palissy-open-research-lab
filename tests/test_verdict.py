"""The mechanical verdict: a result is reported only if the test could have come out the other way
and the answer doesn't depend on the seed."""

import pytest

from palissy.stages.analysis import figures_to_check
from palissy.stages.common import extract_code
from palissy.stages.critic import _parse
from palissy.stages.hypothesis import _json_block, phrasing_problem
from palissy.stages.numbers import numbers_in, unsupported
from palissy.stages.verdict import (Contract, binom_tail, decide, detected, meets,
                                    parse_result)

from .test_pipeline import CONTRACT


def run(effect, p, n=200, successes=None, exit_code=0):
    return {"exit_code": exit_code, "result": {"effect": effect, "p_value": p, "n": n,
                                               "successes": successes}}


def grid(treatment, positive, negative):
    return {"treatment": treatment, "positive": positive, "negative": negative}


C = Contract.parse(CONTRACT)  # alpha 0.05, direction increase, no minimum effect
C01 = Contract.parse({**CONTRACT, "alpha": 0.01})
HIT, MISS = run(0.3, 0.01), run(0.02, 0.6)
POS, NEG = run(0.5, 0.001), run(0.01, 0.7)
CLEAN = grid([HIT] * 5, [POS] * 5, [NEG] * 5)


def test_clean_run_supports_or_refutes_by_rule():
    assert decide(C, CLEAN).verdict == "supports"
    assert decide(C, {**CLEAN, "treatment": [MISS] * 5}).verdict == "refutes"
    # significant, but in the opposite direction to the pre-registered one
    assert decide(C, {**CLEAN, "treatment": [run(-0.3, 0.01)] * 5}).verdict == "refutes"


def test_the_tally_counts_hits_per_arm():
    v = decide(C, grid([HIT] * 4 + [MISS], [POS] * 5, [NEG] * 5))
    assert v.tally["treatment"]["hits"] == 4 and v.tally["treatment"]["ok"] == 5
    assert v.tally["positive"]["hits"] == 5 and v.tally["negative"]["hits"] == 0
    assert v.tally["treatment"]["median_effect"] == 0.3


def test_positive_control_must_be_detected_in_nearly_every_run():
    four = decide(C, grid([HIT] * 5, [POS] * 4 + [run(0.1, 0.4)], [NEG] * 5))
    assert four.verdict == "supports"  # 4 of 5 is enough
    three = decide(C, grid([HIT] * 5, [POS] * 3 + [run(0.1, 0.4)] * 2, [NEG] * 5))
    assert three.verdict == "inconclusive" and "planted on purpose in 2 of 5" in three.reasons[0]


def test_negative_control_false_alarms_are_judged_against_alpha():
    fire, strong = run(0.2, 0.001), run(0.3, 0.0001)
    # at alpha 0.05, 2 false alarms in 5 runs happens ~2% of the time by chance: tolerated
    assert decide(C, grid([HIT] * 5, [POS] * 5, [fire] * 2 + [NEG] * 3)).verdict == "supports"
    # at alpha 0.01 the same two are far rarer than chance allows
    v = decide(C01, grid([strong] * 5, [POS] * 5, [fire] * 2 + [NEG] * 3))
    assert v.verdict == "inconclusive" and "none was planted in 2 of 5" in v.reasons[0]
    # a single fluke at alpha 0.01 is tolerated: this is the run that motivated replicates
    assert decide(C01, grid([strong] * 5, [POS] * 5, [fire] + [NEG] * 4)).verdict == "supports"
    assert binom_tail(0, 5, 0.05) == pytest.approx(1) and 0.04 < binom_tail(1, 5, 0.01) < 0.05


def test_with_fewer_than_three_runs_any_false_alarm_counts():
    one = grid([HIT], [POS], [run(0.2, 0.001)])
    assert decide(C, one).verdict == "inconclusive"
    assert decide(C, grid([HIT], [POS], [NEG])).verdict == "supports"  # a single clean run


def test_p_pinned_at_one_is_inconclusive():
    v = decide(C, {**CLEAN, "treatment": [run(0.0, 1.0)] * 5})
    assert v.verdict == "inconclusive" and any("p = 1" in r for r in v.reasons)


def test_all_or_nothing_counts_are_fixed_by_parameters():
    fixed = grid([run(0.0, 0.5, 2000, 0)] * 5, [run(0.5, 0.001, 2000, 2000)] * 5,
                 [run(0.0, 0.6, 2000, 0)] * 5)
    v = decide(C, fixed)
    assert v.verdict == "inconclusive" and any("fixed by the parameters" in r for r in v.reasons)
    # one run with a real count is enough: the outcome wasn't fixed
    ok = grid([run(0.1, 0.5, 2000, 37)] + [run(0.0, 0.5, 2000, 0)] * 4,
              [run(0.5, 0.001, 2000, 2000)] * 5, [run(0.0, 0.6, 2000, 0)] * 5)
    assert decide(C, ok).verdict == "refutes"


def test_treatment_identical_to_negative_control():
    v = decide(C, {**CLEAN, "treatment": [NEG] * 5})
    assert v.verdict == "inconclusive" and "negative control's number" in v.reasons[0]


def test_a_result_that_flips_between_seeds_is_inconclusive():
    """The treatment sits on the threshold: 2 of 5 seeds cross it, so no run can settle it."""
    v = decide(C, {**CLEAN, "treatment": [HIT] * 2 + [MISS] * 3})
    assert v.verdict == "inconclusive" and "changes with the seed" in v.reasons[-1]
    assert decide(C, {**CLEAN, "treatment": [HIT] * 4 + [MISS]}).verdict == "supports"
    assert decide(C, {**CLEAN, "treatment": [HIT] + [MISS] * 4}).verdict == "refutes"


def test_crashed_branches_are_rolled_back_and_the_survivors_decide():
    crashed = run(0, 0, exit_code=1)
    v = decide(C, grid([HIT] * 3 + [crashed] * 2, [POS] * 5, [NEG] * 5))
    assert v.verdict == "supports" and v.tally["treatment"]["ok"] == 3
    assert "2 rolled back" in v.checks[0].detail
    # too few survivors to read: not enough runs to call it
    thin = decide(C, grid([HIT] * 2 + [crashed] * 3, [POS] * 5, [NEG] * 5))
    assert thin.verdict == "inconclusive" and "Too few runs" in thin.reasons[0]


def test_an_arm_with_no_finished_branch_is_failed():
    crashed = run(0, 0, exit_code=1)
    assert decide(C, grid([crashed] * 5, [POS] * 5, [NEG] * 5)).verdict == "failed"
    assert decide(C, grid([HIT], [], [])).verdict == "failed"  # never reached after a failure


def test_no_contract_or_unreadable_output_is_inconclusive():
    assert decide(None, CLEAN).verdict == "inconclusive"
    silent = {"exit_code": 0, "result": None}
    v = decide(C, {**CLEAN, "treatment": [silent] * 5})
    assert v.verdict == "inconclusive" and "no RESULT_JSON" in v.reasons[0]
    assert decide(C, {**CLEAN, "treatment": [run(0.3, 1.7)] * 5}).verdict == "inconclusive"


def test_a_named_size_must_be_reached_in_each_run_to_count():
    """Hulk run 2: hypothesis said >8-fold, contract only tested direction, result was ~6-fold."""
    big = Contract.parse({**CONTRACT, "min_effect": 7})
    run6 = {**CLEAN, "treatment": [run(5.96, 0.001)] * 5}
    assert decide(big, run6).verdict == "refutes"
    assert decide(Contract.parse({**CONTRACT, "min_effect": 5}), run6).verdict == "supports"
    assert decide(C, run6).verdict == "supports"  # no size named: direction is the claim
    with pytest.raises(ValueError, match="min_effect"):
        Contract.parse({**CONTRACT, "min_effect": -1})


def test_contract_parse_names_what_is_missing():
    with pytest.raises(ValueError, match="positive_control.*direction"):
        Contract.parse({**CONTRACT, "positive_control": "", "direction": "sideways"})
    with pytest.raises(ValueError, match="alpha"):
        Contract.parse({**CONTRACT, "alpha": 0.9})


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
    assert meets({"effect": 0.1, "p_value": 0.01}, c)


def test_parse_result_takes_the_last_valid_line():
    out = ('x\nRESULT_JSON: {"effect": 1, "p_value": 0.5, "n": 3}\n'
           'RESULT_JSON: {"effect": 2, "p_value": 0.1, "n": 3}\n')
    assert parse_result(out)["effect"] == 2
    assert parse_result("RESULT: supports") is None
    assert parse_result("RESULT_JSON: {not json}") is None
    assert parse_result('RESULT_JSON:{"effect": 1, "p_value": 0.5, "n": 3}')["n"] == 3


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
    assert "effect_not_typed_in" in answers
    assert _parse('{"level": "weird"}')[0] == "concern"


# --- figures quoted in the analyst's prose -----------------------------------------------


def test_figures_that_match_no_output_number_are_flagged():
    v = decide(C, {**CLEAN, "treatment": [run(3.2, 0.0001)] * 5})
    # the real Hulk misreading: a 320% effect described as "well under 200%"
    bad = figures_to_check("Mass rose by 3.2, well under 200% of wild type.",
                           "Knockout increases mass by >300%", "", CONTRACT, v)
    assert bad == ["200"]
    assert figures_to_check("Effect 3.2 (320%), p about 0.0001 in 5 of 5 runs, versus the "
                            "pre-registered 300%.", "Knockout increases mass by >300%", "",
                            CONTRACT, v) == []


def test_small_counts_and_rounding_are_not_flagged():
    assert [v for _, v in numbers_in("5 of 5 runs, p = 9.999e-05, −0.295, 1,000 shuffles")] == [
        5, 5, 9.999e-05, -0.295, 1000]
    allowed = {0.2953, 29.53, 1000.0}
    assert unsupported("a 29.5% drop after 1,000 shuffles over three arms", allowed) == []
    assert unsupported("a 41% drop", allowed) == ["41"]
