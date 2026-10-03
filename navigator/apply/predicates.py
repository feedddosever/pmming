"""Coverage conditions with three-valued (Kleene) logic.

A rule's coverage is::

    {"applies_if": [clause, ...],                 # AND
     "exemptions": [{"label": str, "all": [clause, ...]}, ...],  # rule excluded if ANY group is true
     "text": "original wording"}

A clause is ``{"fact", "op", "value_number", "value_text", "value_list"}``. Facts the address data
does not contain evaluate to UNKNOWN, but Kleene logic still lets known facts decide, e.g. an
exemption "single-family home AND owner is a natural person" is FALSE for a 20-unit building
even though owner type is unknown.

Numeric facts are handled as closed intervals so that date-relative tests (building age) and
year-only data against a full date (certificate of occupancy before 6/13/1979) return UNKNOWN
exactly on the boundary year instead of guessing.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

TRUE, FALSE, UNKNOWN = True, False, None


def k_and(values) -> bool | None:
    values = list(values)
    if any(v is FALSE for v in values):
        return FALSE
    if all(v is TRUE for v in values):
        return TRUE
    return UNKNOWN


def k_or(values) -> bool | None:
    values = list(values)
    if any(v is TRUE for v in values):
        return TRUE
    if all(v is FALSE for v in values):
        return FALSE
    return UNKNOWN


def k_not(v):
    return UNKNOWN if v is UNKNOWN else (not v)


def _num(x):
    if x is None or x == "":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _interval(fact: str, facts: dict, as_of: date):
    """Return (lo, hi) bounds for a numeric fact, or None when unknown."""
    if fact == "age_years":
        yb = _num(facts.get("year_built"))
        if yb is None:
            return None
        # Built some time during year yb; as_of is a precise date.
        yb = int(yb)
        try:
            return ((as_of - date(yb, 12, 31)).days / 365.2425, (as_of - date(yb, 1, 1)).days / 365.2425)
        except ValueError:
            return None
    v = _num(facts.get(fact))
    return None if v is None else (v, v)


def _cmp_interval(lo: float, hi: float, op: str, x: float):
    def test(v):
        return {"lt": v < x, "lte": v <= x, "gt": v > x, "gte": v >= x, "eq": v == x, "ne": v != x}[op]

    if op in ("eq", "ne") and lo != hi:
        inside = lo <= x <= hi
        if op == "eq":
            return UNKNOWN if inside else FALSE
        return UNKNOWN if inside else TRUE
    a, b = test(lo), test(hi)
    return a if a == b else UNKNOWN


def _parse_cutoff(text: str):
    t = str(text).strip()
    try:
        return date.fromisoformat(t[:10])
    except ValueError:
        pass
    if re.fullmatch(r"\d{4}", t):
        return date(int(t), 1, 1)
    return None


def eval_clause(clause: dict, facts: dict, as_of: date):
    fact, op = clause.get("fact"), clause.get("op")
    num, text, lst = clause.get("value_number"), clause.get("value_text"), clause.get("value_list") or []

    if op == "before_date":  # e.g. year_built vs certificate-of-occupancy cutoff date
        yb = _num(facts.get(fact))
        if yb is None or not text:
            return UNKNOWN
        cutoff = _parse_cutoff(text)
        if cutoff is None:
            return UNKNOWN
        if yb < cutoff.year:
            return TRUE
        if yb > cutoff.year:
            return FALSE
        return UNKNOWN if (cutoff.month, cutoff.day) != (1, 1) else FALSE

    if op in ("lt", "lte", "gt", "gte", "eq", "ne") and num is not None:
        iv = _interval(fact, facts, as_of)
        if iv is None:
            return UNKNOWN
        return _cmp_interval(iv[0], iv[1], op, float(num))

    value = facts.get(fact)
    if value is None or value == "":
        return UNKNOWN
    sval = str(value).strip().lower()
    if op in ("in", "not_in"):
        members = {str(m).strip().lower() for m in lst}
        hit = sval in members
        return hit if op == "in" else (not hit)
    if op in ("eq", "ne") and text is not None:
        hit = sval == str(text).strip().lower()
        return hit if op == "eq" else (not hit)
    if op == "is_true":
        return sval in ("1", "true", "yes", "y")
    if op == "is_false":
        return sval in ("0", "false", "no", "n")
    return UNKNOWN


def evaluate(coverage: dict | None, facts: dict, as_of: date) -> tuple[Any, list[str]]:
    """Return (TRUE|FALSE|UNKNOWN, reasons)."""
    coverage = coverage or {}
    reasons: list[str] = []
    base_vals = []
    for c in coverage.get("applies_if") or []:
        v = eval_clause(c, facts, as_of)
        base_vals.append(v)
        if v is not TRUE:
            reasons.append(f"condition \"{_describe(c)}\" is {_word(v)}")
    base = k_and(base_vals)

    ex_vals = []
    for ex in coverage.get("exemptions") or []:
        if not ex.get("all"):
            continue  # an exemption with no stated condition must not exempt everything
        v = k_and(eval_clause(c, facts, as_of) for c in ex.get("all") or [])
        ex_vals.append(v)
        if v is not FALSE:
            reasons.append(f"exemption '{ex.get('label', 'exemption')}' is {_word(v)}")
    exempt = k_or(ex_vals) if ex_vals else FALSE
    return k_and([base, k_not(exempt)]), reasons


def _word(v):
    return "unknown (the data does not say)" if v is UNKNOWN else ("met" if v else "not met")


_FACT = {"year_built": "year built", "age_years": "building age (years)", "units": "number of units",
         "use_code": "use code", "building_type": "building type", "owner_type": "owner type",
         "owner_units_owned": "units the owner owns", "subsidized": "subsidized housing", "other": "condition"}
_OP = {"lt": "under", "lte": "at most", "gt": "over", "gte": "at least", "eq": "is", "ne": "is not",
       "in": "is one of", "not_in": "is not one of", "is_true": "is true", "is_false": "is false"}


def _describe(c: dict) -> str:
    fact, op = c.get("fact"), c.get("op")
    if op == "before_date":
        return f"built before {c.get('value_text')}"
    val = c.get("value_number")
    if isinstance(val, float) and val.is_integer():
        val = int(val)
    if val is None:
        val = c.get("value_text")
    if val is None:
        val = ", ".join(c.get("value_list") or [])
    return f"{_FACT.get(fact, fact)} {_OP.get(op, op)} {val}".strip()
