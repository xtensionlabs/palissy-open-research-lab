"""Pre-registration contract and the mechanical verdict. No model decides the verdict.

Before anything runs, the experiment design commits to a contract: what is measured, the test,
the null, the threshold, the predicted direction, and a positive and a negative control. The
script then runs as a grid of sandbox branches, `replicates` seeds for each of three arms
(treatment, positive control, negative control), and each branch prints one machine-readable
line:

    RESULT_JSON: {"arm": "treatment", "effect": 0.31, "p_value": 0.004, "n": 400, "successes": null}

`decide` reads the grid against the contract. A result is only reported as supports or refutes
if the test could have come out the other way and the answer doesn't depend on the seed:

  - the positive control is detected in nearly every replicate (the test can find an effect),
  - the negative control's false alarms are no more frequent than the alpha level allows,
  - the numbers are not fixed by the parameters,
  - the treatment gives the same answer in nearly every replicate.

One lucky or unlucky draw can't decide any of these, which is why a single seed isn't enough.
"""

import hashlib
import json
import math
import re
import statistics
from dataclasses import asdict, dataclass, field

ARMS = ("treatment", "positive", "negative")
DIRECTIONS = ("increase", "decrease", "any")
DEGENERATE_P = 0.999  # a p-value this close to 1 means the test had no chance to find anything
AGREEMENT = 0.8  # share of replicates that must agree for a verdict, and for a control to pass
QUORUM = 0.6  # share of an arm's replicates that must produce a readable result
CONTROL_CHANCE = 0.01  # fault a control only if its false alarms would be rarer than this by chance
_RESULT = re.compile(r"^RESULT_JSON:\s*(\{.*\})\s*$", re.M)


@dataclass
class Contract:
    statistic: str
    test: str
    null: str
    alpha: float
    direction: str
    supports_if: str
    refutes_if: str
    positive_control: str
    negative_control: str
    # Smallest effect, on the script's own `effect` scale, that counts as support. A hypothesis
    # that names a size ("more than 8-fold") must set it, or a mere direction would "support" it.
    min_effect: float = 0.0

    @classmethod
    def parse(cls, data: dict) -> "Contract":
        """Raise ValueError naming every missing or malformed field."""
        text_fields = [f for f in cls.__dataclass_fields__
                       if f not in ("alpha", "direction", "min_effect")]
        missing = [f for f in text_fields if not str(data.get(f) or "").strip()]
        try:
            alpha = float(data.get("alpha", 0.05))
        except (TypeError, ValueError):
            alpha = -1.0
        if not 0 < alpha < 0.5:
            missing.append("alpha (must be between 0 and 0.5)")
        direction = str(data.get("direction", "")).strip().lower()
        if direction not in DIRECTIONS:
            missing.append(f"direction (one of {', '.join(DIRECTIONS)})")
        min_effect = _num(data.get("min_effect") or 0)
        if min_effect is None or min_effect < 0:
            missing.append("min_effect (a number, 0 or more)")
        if missing:
            raise ValueError("pre-registration incomplete: " + ", ".join(missing))
        return cls(alpha=alpha, direction=direction, min_effect=min_effect,
                   **{f: _flatten(data[f]) for f in text_fields})

    def fingerprint(self, hypothesis: str) -> str:
        """Hash of hypothesis + contract, frozen when the researcher approves the design.

        The code is hashed separately: a crash repair may change the code, never the contract.
        """
        blob = hypothesis.strip() + "\n" + json.dumps(asdict(self), sort_keys=True)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _flatten(value) -> str:
    """Models sometimes nest a field ({"effect_planted": ..., "size": ...}); keep the words."""
    if isinstance(value, dict):
        return "; ".join(_flatten(v) for v in value.values() if _flatten(v))
    if isinstance(value, list):
        return "; ".join(_flatten(v) for v in value if _flatten(v))
    return str(value).strip()


def parse_result(stdout: str) -> dict | None:
    """The last RESULT_JSON line of one branch's output, or None if absent or unreadable."""
    matches = _RESULT.findall(stdout or "")
    if not matches:
        return None
    try:
        data = json.loads(matches[-1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


@dataclass
class Check:
    name: str
    passed: bool
    detail: str


@dataclass
class Verdict:
    verdict: str  # supports | refutes | inconclusive | failed
    reasons: list[str] = field(default_factory=list)  # plain-English, empty when clean
    checks: list[Check] = field(default_factory=list)
    # arm -> {"total", "ok", "hits", "median_effect", "median_p"}. For the treatment, a hit is a
    # run that was significant, in the predicted direction and at least `min_effect`; for the
    # controls it is a run where the test fired.
    tally: dict[str, dict] = field(default_factory=dict)


def _num(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _readable(r: dict | None) -> str | None:
    """Why one branch's result can't be used, or None if it can."""
    if r is None:
        return "no RESULT_JSON line"
    p, effect = _num(r.get("p_value")), _num(r.get("effect"))
    if effect is None:
        return "effect is not a number"
    if p is None or not 0 <= p <= 1:
        return "p_value is not a number between 0 and 1"
    n = _num(r.get("n"))
    if n is None or n < 2:
        return "n is missing or below 2"
    return None


def detected(r: dict, c: Contract) -> bool:
    """Significant at the pre-registered alpha, in the pre-registered direction."""
    effect, p = float(r["effect"]), float(r["p_value"])
    if p >= c.alpha:
        return False
    return {"increase": effect > 0, "decrease": effect < 0, "any": effect != 0}[c.direction]


def meets(r: dict, c: Contract) -> bool:
    """Detected, and at least as large as the pre-registered minimum effect."""
    return detected(r, c) and (c.min_effect <= 0 or abs(float(r["effect"])) >= c.min_effect)


def is_hit(arm: str, result: dict | None, c: Contract) -> bool:
    """Whether one run counts as a hit for its arm: the treatment must also reach min_effect."""
    if result is None or _readable(result) is not None:
        return False
    return meets(result, c) if arm == "treatment" else detected(result, c)


def binom_tail(k: int, n: int, p: float) -> float:
    """P(X >= k) for X ~ Binomial(n, p): how often chance alone gives k or more false alarms."""
    return sum(math.comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k, n + 1))


def _need(n: int) -> int:
    return math.ceil(AGREEMENT * n - 1e-9)


def decide(contract: Contract | None, arms: dict[str, list[dict]]) -> Verdict:
    """arms: arm -> one {"exit_code": int, "result": parsed RESULT_JSON or None} per replicate."""
    checks: list[Check] = []
    tally: dict[str, dict] = {}

    def check(name: str, passed: bool, detail: str) -> bool:
        checks.append(Check(name, passed, detail))
        return passed

    totals = {a: len(arms.get(a, [])) for a in ARMS}
    finished = {a: [r for r in arms.get(a, []) if r.get("exit_code") == 0] for a in ARMS}
    for a in ARMS:
        tally[a] = {"total": totals[a], "ok": 0, "hits": 0, "median_effect": None,
                    "median_p": None}

    dead = [a for a in ARMS if not finished[a]]
    if dead:
        check("Ran", False, f"No {', '.join(dead)} branch finished cleanly.")
        return Verdict("failed", [f"No {', '.join(dead)} run finished, so there is nothing to "
                                  "read."], checks, tally)
    n_branch, n_fin = sum(totals.values()), sum(len(v) for v in finished.values())
    check("Ran", True, f"{n_fin} of {n_branch} branches finished"
          + (f"; {n_branch - n_fin} rolled back." if n_fin < n_branch else "."))

    if contract is None:
        check("Pre-registered", False, "No complete pre-registration.")
        return Verdict("inconclusive", ["Nothing was committed before the run, so there is no "
                                        "stated test to hold the result to."], checks, tally)
    check("Pre-registered", True, f"Alpha {contract.alpha:g}, direction {contract.direction}.")

    good: dict[str, list[dict]] = {}
    problems: list[str] = []
    for a in ARMS:
        rows = [r["result"] for r in finished[a] if _readable(r.get("result")) is None]
        good[a] = rows
        if len(rows) < max(1, math.ceil(QUORUM * totals[a] - 1e-9)):
            why = next((_readable(r.get("result")) for r in finished[a]
                        if _readable(r.get("result"))), "too few runs")
            problems.append(f"{a}: {len(rows)} of {totals[a]} readable ({why})")
        if rows:
            tally[a].update(ok=len(rows),
                            median_effect=statistics.median(float(r["effect"]) for r in rows),
                            median_p=statistics.median(float(r["p_value"]) for r in rows))
    if problems:
        check("Readable", False, "; ".join(problems) + ".")
        return Verdict("inconclusive", ["Too few runs produced a result that could be read ("
                                        + "; ".join(problems) + ")."], checks, tally)
    check("Readable", True, "Every arm reported effect, p and n in enough runs.")

    reasons: list[str] = []
    pos, neg, trt = good["positive"], good["negative"], good["treatment"]
    tally["positive"]["hits"] = sum(detected(r, contract) for r in pos)
    tally["negative"]["hits"] = sum(detected(r, contract) for r in neg)
    tally["treatment"]["hits"] = sum(meets(r, contract) for r in trt)

    hits, n = tally["positive"]["hits"], len(pos)
    if not check("Positive control", hits >= _need(n),
                 f"Planted effect found in {hits} of {n} runs "
                 f"(median effect {tally['positive']['median_effect']:.4g})."):
        reasons.append(f"The test missed an effect planted on purpose in {n - hits} of {n} "
                       "runs, so it can't be trusted to detect a real one.")

    fp, n = tally["negative"]["hits"], len(neg)
    chance = binom_tail(fp, n, contract.alpha) if fp else 1.0
    # With fewer than three runs a false-alarm rate can't be judged, so any false alarm counts.
    fine = fp == 0 if n < 3 else chance >= CONTROL_CHANCE
    if not check("Negative control", fine,
                 f"False alarm in {fp} of {n} runs where nothing was planted"
                 + (f" (chance alone gives this or worse {chance:.1%} of the time)." if fp else
                    ".")):
        reasons.append(f"The test found an effect where none was planted in {fp} of {n} runs, "
                       f"more often than alpha {contract.alpha:g} allows, so a positive result "
                       "would mean little.")

    p_med = tally["treatment"]["median_p"]
    if not check("p not pinned", p_med < DEGENERATE_P, f"Median treatment p = {p_med:.3g}."):
        reasons.append(f"p = {p_med:.3g}: the test could not have found anything, whatever "
                       "the data. Check that the null is a real null.")

    counted = [a for a in ARMS if good[a] and all(_num(r.get("successes")) is not None
                                                  for r in good[a])]
    if len(counted) == len(ARMS):
        pinned = all(_num(r["successes"]) in (0, _num(r["n"])) for a in ARMS for r in good[a])
        if not check("Outcome not fixed", not pinned,
                     ", ".join(f"{a} {int(float(good[a][0]['successes']))}/"
                               f"{int(float(good[a][0]['n']))}" for a in ARMS)
                     + " in the first replicate."):
            reasons.append("Every arm came out all-or-nothing (0 of N or N of N): the outcome "
                           "was fixed by the parameters before it ran.")

    med = {a: tally[a]["median_effect"] for a in ARMS}
    varied = len(set(med.values())) > 1
    same_as_null = med["treatment"] == med["negative"] and (
        tally["treatment"]["median_p"] == tally["negative"]["median_p"])
    if not check("Arms differ", varied and not same_as_null,
                 "Median effects " + ", ".join(f"{a} {e:.4g}" for a, e in med.items()) + "."):
        reasons.append("The treatment arm gave exactly the negative control's number, so it "
                       "isn't testing anything different." if varied else
                       "All three arms gave the same number, so the test can't tell them apart.")

    k, n = tally["treatment"]["hits"], len(trt)
    stable = k >= _need(n) or (n - k) >= _need(n)
    size = (f" and at least {contract.min_effect:g}" if contract.min_effect > 0 else "")
    if not check("Same answer across seeds", stable,
                 f"Treatment significant{size} in {k} of {n} runs."):
        reasons.append(f"The treatment result changes with the seed (significant{size} in {k} "
                       f"of {n} runs), so it sits on the decision boundary and one run can't "
                       "settle it.")

    if reasons:
        return Verdict("inconclusive", reasons, checks, tally)
    return Verdict("supports" if k >= _need(n) else "refutes", [], checks, tally)
