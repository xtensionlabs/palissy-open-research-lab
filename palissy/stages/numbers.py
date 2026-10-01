"""Check that figures quoted in the analyst's prose appear in the run's own output.

The verdict comes from rules, but the write-up is still model prose, and a model can misread a
number ("well under 200%" for a 320% effect). This doesn't judge the claim; it flags figures
that match nothing the run produced, the pre-registration or the hypothesis, so the researcher
checks them.
"""

import re

_NUM = re.compile(r"(?<![\w.])[-−–]?\d[\d,]*(?:\.\d+)?(?:[eE][-+]?\d+)?")
TRIVIAL = 12  # small whole numbers are counts of things ("three arms"), not claims


def numbers_in(text: str) -> list[tuple[str, float]]:
    """Every figure in the text as (as written, value)."""
    out = []
    for m in _NUM.finditer(text or ""):
        raw = m.group(0)
        try:
            out.append((raw, float(raw.replace(",", "").replace("−", "-")
                                   .replace("–", "-"))))
        except ValueError:
            continue
    return out


def _forms(v: float) -> set[float]:
    """A value as it might be written: raw, absolute, as a percent, as a fold change."""
    a = abs(v)
    return {v, a, a * 100, a / 100, 1 + v, 1 + a, a + 1 if a < 1 else a}


def allowed_values(texts: list[str], values: list[float]) -> set[float]:
    allowed: set[float] = set()
    for t in texts:
        for _, v in numbers_in(t):
            allowed |= _forms(v)
    for v in values:
        allowed |= _forms(v)
    # differences between arms are quoted too ("0.22 above the null")
    for i, x in enumerate(values):
        for y in values[i + 1:]:
            allowed |= _forms(x - y)
    return allowed


def unsupported(prose: str, allowed: set[float]) -> list[str]:
    """Figures in `prose` that match none of the allowed values (2% or 0.005 tolerance)."""
    bad: list[str] = []
    for raw, v in numbers_in(prose):
        if float(v).is_integer() and abs(v) <= TRIVIAL:
            continue
        if any(abs(v - a) <= max(0.02 * abs(a), 0.005) for a in allowed):
            continue
        if raw not in bad:
            bad.append(raw)
    return bad
