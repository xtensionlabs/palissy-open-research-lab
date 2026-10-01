"""Pre-registration contract and the mechanical verdict. No model decides the verdict.

Before anything runs, the experiment design commits to a contract: what is measured, the test,
the null, the threshold, the predicted direction, and a positive and a negative control. The
script runs once per arm and prints one machine-readable line:

    RESULT_JSON: {"arm": "treatment", "effect": 0.31, "p_value": 0.004, "n": 400, "successes": null}

`decide` reads the three arms against the contract. A result is only reported as supports or
refutes if the test could have come out the other way: the positive control must be detected,
the negative control must not be, and the numbers must not be fixed by the parameters.
"""

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, field

ARMS = ("treatment", "positive", "negative")
DIRECTIONS = ("increase", "decrease", "any")
DEGENERATE_P = 0.999  # a p-value this close to 1 means the test had no chance to find anything
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
    """The last RESULT_JSON line of one arm's output, or None if absent or unreadable."""
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


def _num(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _readable(r: dict | None) -> str | None:
    """Why an arm's result can't be used, or None if it can."""
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


def decide(contract: Contract | None, arms: dict[str, dict]) -> Verdict:
    """arms: arm -> {"exit_code": int, "result": parsed RESULT_JSON or None}."""
    checks: list[Check] = []

    def check(name: str, passed: bool, detail: str) -> bool:
        checks.append(Check(name, passed, detail))
        return passed

    crashed = [a for a in ARMS if arms.get(a, {}).get("exit_code", 1) != 0]
    if crashed:
        check("Ran", False, f"Did not finish cleanly: {', '.join(crashed)}.")
        return Verdict("failed", [f"The {', '.join(crashed)} arm did not finish, so there is "
                                  "nothing to read."], checks)
    check("Ran", True, "All three arms finished.")

    if contract is None:
        check("Pre-registered", False, "No complete pre-registration.")
        return Verdict("inconclusive", ["Nothing was committed before the run, so there is no "
                                        "stated test to hold the result to."], checks)
    check("Pre-registered", True, f"Alpha {contract.alpha:g}, direction {contract.direction}.")

    bad = {a: why for a in ARMS if (why := _readable(arms[a].get("result")))}
    if bad:
        detail = "; ".join(f"{a}: {why}" for a, why in bad.items())
        check("Readable", False, detail + ".")
        return Verdict("inconclusive", [f"The script's output couldn't be read ({detail})."],
                       checks)
    check("Readable", True, "Every arm reported effect, p and n.")

    r = {a: arms[a]["result"] for a in ARMS}
    reasons: list[str] = []

    pos = detected(r["positive"], contract)
    if not check("Positive control", pos,
                 f"Planted effect {'found' if pos else 'missed'} "
                 f"(effect {_num(r['positive']['effect']):.4g}, p {_num(r['positive']['p_value']):.3g})."):
        reasons.append("The test missed an effect planted on purpose, so it could not have "
                       "detected a real one either.")

    neg = not detected(r["negative"], contract)
    if not check("Negative control", neg,
                 f"{'No effect found' if neg else 'Effect found'} where none exists "
                 f"(p {_num(r['negative']['p_value']):.3g})."):
        reasons.append("The test found an effect where none exists, so a positive result "
                       "would mean nothing.")

    p_t = float(r["treatment"]["p_value"])
    if not check("p not pinned", p_t < DEGENERATE_P, f"Treatment p = {p_t:.3g}."):
        reasons.append(f"p = {p_t:.3g}: the test could not have found anything, whatever the "
                       "data. Check that the null is a real null.")

    counted = [a for a in ARMS if _num(r[a].get("successes")) is not None]
    if len(counted) == len(ARMS):
        pinned = [a for a in ARMS if _num(r[a]["successes"]) in (0, _num(r[a]["n"]))]
        if not check("Outcome not fixed", len(pinned) < len(ARMS),
                     ", ".join(f"{a} {int(float(r[a]['successes']))}/{int(float(r[a]['n']))}"
                               for a in ARMS) + "."):
            reasons.append("Every arm came out all-or-nothing (0 of N or N of N): the outcome "
                           "was fixed by the parameters before it ran.")

    effects = [float(r[a]["effect"]) for a in ARMS]
    varied = len(set(effects)) > 1
    same_as_null = effects[0] == effects[2] and float(r["treatment"]["p_value"]) == float(
        r["negative"]["p_value"])
    if not check("Arms differ", varied and not same_as_null,
                 "Effects " + ", ".join(f"{a} {e:.4g}" for a, e in zip(ARMS, effects)) + "."):
        reasons.append("The treatment arm gave exactly the negative control's number, so it "
                       "isn't testing anything different." if varied else
                       "All three arms gave the same number, so the test can't tell them apart.")

    if reasons:
        return Verdict("inconclusive", reasons, checks)
    supports = detected(r["treatment"], contract)
    if supports and contract.min_effect > 0:
        size = abs(float(r["treatment"]["effect"]))
        supports = check("Effect size", size >= contract.min_effect,
                         f"Treatment effect {size:.4g} against the pre-registered minimum "
                         f"{contract.min_effect:g}.")
    return Verdict("supports" if supports else "refutes", [], checks)
