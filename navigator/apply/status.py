"""Legal status of a rule on a given date ("as of" engine)."""
from __future__ import annotations

from datetime import date

IN_FORCE = "in_force"
NOT_YET_EFFECTIVE = "not_yet_effective"
PENDING = "pending"
STRUCK = "struck"
EXPIRED = "expired"


def _d(s):
    if not s:
        return None
    try:
        return date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def status_on(rule: dict, as_of: date) -> str:
    status = (rule.get("status") or "enacted").lower()
    if status in ("struck", "repealed", "failed", "invalidated", "withdrawn"):
        return STRUCK
    if status in ("pending", "proposed", "introduced"):
        return PENDING
    eff, end = _d(rule.get("effective_date")), _d(rule.get("end_date"))
    if end and as_of >= end:
        return EXPIRED
    if eff and as_of < eff:
        return NOT_YET_EFFECTIVE
    return IN_FORCE


def boundary_dates(rules: list[dict]) -> list[date]:
    """Every date on which some rule's status can change."""
    out = set()
    for r in rules:
        for k in ("effective_date", "end_date"):
            d = _d(r.get(k))
            if d:
                out.add(d)
    return sorted(out)
