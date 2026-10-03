"""Address x rules -> lookup results.

Result values (brief): applies | unknown | superseded | not_yet_effective | pending.
Rules that do not apply are omitted. Struck/expired rules are never exported as law.

Precedence follows the extracted text, never a blanket "local beats state":
* A rule with ``yields_to: [{"category", "level"}]`` becomes ``superseded`` only when a same-category
  rule at that level in the address's stack *applies*; if that local rule is ``unknown``, the
  yielding rule is downgraded to ``unknown`` (we cannot tell which one governs).
* Conflicts come only from extracted ``may_preempt`` clauses and are flagged on both rules for every
  address whose stack contains both, regardless of the as-of date (the T3 situation).
"""
from __future__ import annotations

from datetime import date

from . import predicates, status as st
from ..resolve.jurisdictions import label

P_TRUE, P_FALSE = True, False


def _level(jid: str) -> str:
    parts = jid.split(":")
    return "state" if len(parts) == 1 else parts[1]


def evaluate_address(address: dict, rules: list[dict], as_of: date, *, assume_enacted: set[str] | None = None) -> list[dict]:
    """Return exported results for one address. ``assume_enacted`` = rule ids treated as enacted
    (used for "what if this pending bill passes" change tracking)."""
    assume_enacted = assume_enacted or set()
    stack = address.get("stack") or []
    facts = address.get("facts") or {}
    candidates = [r for r in rules if r.get("kind", "rule") == "rule" and r["jurisdiction"]["id"] in stack]

    raw: dict[str, dict] = {}
    for r in candidates:
        rr = dict(r)
        if r["rule_id"] in assume_enacted:
            rr["status"] = "enacted"
        s = st.status_on(rr, as_of)
        if s in (st.STRUCK, st.EXPIRED):
            continue
        cov, reasons = predicates.evaluate(r.get("coverage"), facts, as_of)
        if cov is P_FALSE:
            continue
        if s == st.PENDING:
            result = "pending"
        elif s == st.NOT_YET_EFFECTIVE:
            result = "not_yet_effective"
        else:
            result = "applies" if cov is P_TRUE else "unknown"
        raw[r["rule_id"]] = {"rule": r, "result": result, "reasons": reasons, "flags": []}

    # Precedence (only in-force rules can displace another rule).
    for rid, entry in raw.items():
        r = entry["rule"]
        if entry["result"] not in ("applies", "unknown"):
            continue
        for y in r.get("yields_to") or []:
            locals_ = [
                e for e in raw.values()
                if e["rule"]["category"] == y.get("category", r["category"])
                and _level(e["rule"]["jurisdiction"]["id"]) == (y.get("level") or "city")
                and e["rule"]["rule_id"] != rid
                and e["result"] in ("applies", "unknown")
            ]
            if any(e["result"] == "applies" for e in locals_):
                winner = next(e for e in locals_ if e["result"] == "applies")["rule"]
                entry["result"] = "superseded"
                entry["reasons"].append(f"yields to {winner['citation']} ({label(winner['jurisdiction']['id'])})")
                entry["superseded_by"] = winner["rule_id"]
                break
            if locals_ and entry["result"] == "applies":
                entry["result"] = "unknown"
                entry["reasons"].append("may yield to a local rule whose coverage is unknown for this building")

    # Conflicts (from extracted preemption language only).
    for r in candidates:
        for p in r.get("may_preempt") or []:
            for other in candidates:
                if other is r or other["category"] != p.get("category", r["category"]):
                    continue
                if _level(other["jurisdiction"]["id"]) != (p.get("level") or "city"):
                    continue
                if st.status_on(other, as_of) in (st.STRUCK, st.EXPIRED):
                    continue
                for a, b in ((r, other), (other, r)):
                    if a["rule_id"] in raw:
                        flag = {"type": "conflict", "with": b["rule_id"], "note": p.get("note") or "possible preemption"}
                        if flag not in raw[a["rule_id"]]["flags"]:
                            raw[a["rule_id"]]["flags"].append(flag)

    out = []
    for rid, e in raw.items():
        r = e["rule"]
        src = r.get("source") or {}
        if r.get("flags"):
            e["flags"].extend({"type": f} for f in r["flags"] if isinstance(f, str))
        out.append({
            "rule_id": rid,
            "category": r["category"],
            "jurisdiction": r["jurisdiction"]["id"],
            "result": e["result"],
            "citation": r.get("citation"),
            "quote": src.get("quote"),
            "source_doc": src.get("doc_id"),
            "retrieval_date": src.get("retrieval_date"),
            "effective_date": r.get("effective_date"),
            "status": r.get("status"),
            "confidence": r.get("confidence"),
            "reasons": e["reasons"],
            "flags": e["flags"],
            **({"superseded_by": e["superseded_by"]} if "superseded_by" in e else {}),
        })
    out.sort(key=lambda x: (x["category"], x["jurisdiction"], x["rule_id"]))
    return out


def no_rule_findings(address: dict, rules: list[dict]) -> list[dict]:
    stack = address.get("stack") or []
    return [
        {"rule_id": r["rule_id"], "category": r["category"], "jurisdiction": r["jurisdiction"]["id"],
         "result": "no_rule", "citation": r.get("citation"), "quote": (r.get("source") or {}).get("quote")}
        for r in rules if r.get("kind") == "no_rule" and r["jurisdiction"]["id"] in stack
    ]
