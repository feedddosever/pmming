"""Second-pass review of risky extracted rules (same model access as extraction).

First-pass extraction errs in a few predictable ways. Rules showing those patterns are sent back,
with their source document, under stricter guidance. The reviewer may keep, correct or drop
each rule. Nothing is edited by hand; every decision is logged in the audit ledger.
"""
from __future__ import annotations

import json
import re

from .. import config
from ..audit import ledger
from . import llm, prompts

REVIEW_PROPS = {
    "decision": {"type": "string", "enum": ["keep", "correct", "drop"]},
    "reason": {"type": "string"},
    "rule": {"type": "object", "properties": prompts.RULE_PROPS, "required": list(prompts.RULE_PROPS),
             "additionalProperties": False},
}
REVIEW_SCHEMA = {"type": "object", "properties": REVIEW_PROPS, "required": list(REVIEW_PROPS),
                 "additionalProperties": False}

REVIEW_SYSTEM = f"""You review one rule record that was extracted from an official legal document. Check it
against the document and the strict rules below. Return decision "keep" (record is right; return it unchanged),
"correct" (return the corrected record), or "drop" (the record should not exist). Always return a complete
record in "rule" (for "drop", return the original).

{prompts.CATEGORY_GUIDE}

Strict rules:
1. end_date: set ONLY when the text says the law itself expires, sunsets, is repealed or is replaced on that date.
   Annual adjustment periods, allowance years, filing windows and amendment dates are NOT end dates: the rule
   continues; describe the current period in key_value instead and set end_date to null.
2. may_preempt: set ONLY when the text states that this law preempts, supersedes or prohibits local rules on the
   same subject (for example, a state ban on local rent control). Exemptions for certain buildings, carve-outs that
   defer to more protective local ordinances, and partial overrides of less protective local ordinances are not
   preemption; leave may_preempt empty for those.
3. yields_to: set only when the text says this rule does not apply where a local ordinance applies.
4. just_cause_eviction is only for rules that limit the reasons a landlord may evict or refuse to renew.
   Notice periods, notification requirements and procedural rules alone do not qualify: drop them.
5. citation must be stated in the document. If the document names the law but not a code section, cite the name
   the document uses. Never infer a chapter or section number that is not in the text.
6. Drop the record if the document only mentions the rule in passing without stating what it requires.
7. Keep the quote verbatim from the document; if you change it, copy it character for character.
8. status and effective_date follow the document: enacted (even if effective later), pending, or struck.
   A local ordinance whose amended text states its own effective date is enacted; mark it pending only when
   the document shows it has not been adopted.
9. If an enacted statute or bill states no effective date, apply a default only when it is a general rule of law:
   California statutes enacted in a regular session take effect on January 1 of the following year
   (Cal. Const. art. IV, sec. 8(c)) unless the text says otherwise. Effective dates stated relative to approval
   ("first day of the fourth month next following") are computed from the approval date in the document.
   Otherwise leave effective_date null.
"""


def needs_review(rule: dict, doc_text: str) -> list[str]:
    why = []
    if rule.get("end_date"):
        why.append("has end_date")
    if rule.get("may_preempt"):
        why.append("has may_preempt")
    if rule["category"] == "just_cause_eviction" and (rule.get("confidence") or 0) < 0.7:
        why.append("low-confidence just-cause rule")
    if (rule.get("confidence") or 0) < 0.6:
        why.append("low confidence")
    if rule["category"] == "just_cause_eviction" and re.search(
            r"(?i)notif|notice", " ".join(str(rule.get(k) or "") for k in ("title", "requirement"))):
        why.append("just-cause rule that may only concern notices")
    if rule.get("status") == "pending" and ":" in rule["jurisdiction"]["id"]:
        why.append("pending local ordinance")
    if rule.get("status") == "enacted" and not rule.get("effective_date") and re.search(
            r"\b(AB|SB|A\.B\.|S\.B\.|P\.L\.|H\.|S\.)\s?\d", rule.get("citation") or ""):
        why.append("enacted bill without effective date")
    nums = re.findall(r"\d+(?:\.\d+)+|\d{2,}", rule.get("citation") or "")
    if any(n not in doc_text for n in nums):
        why.append("citation number not found in document")
    return why


def _raw(rule: dict) -> dict:
    """Internal record -> the extraction schema shape the reviewer edits."""
    cov = rule.get("coverage") or {}
    jid = rule["jurisdiction"]["id"]
    st = jid.split(":")[0]
    level = "state" if ":" not in jid else jid.split(":")[1]
    name = rule["jurisdiction"].get("label", jid)
    return {
        "category": rule["category"], "jurisdiction_level": level if level in ("state", "county", "city") else "city",
        "jurisdiction_state": st, "jurisdiction_name": name.replace("City and County of ", "").replace("City of ", ""),
        "title": rule.get("title") or "", "citation": rule.get("citation") or "",
        "requirement": rule.get("requirement") or "", "requirement_es": rule.get("requirement_es") or "",
        "key_value": rule.get("key_value"), "coverage_text": cov.get("text") or "",
        "applies_if": cov.get("applies_if") or [], "exemptions": cov.get("exemptions") or [],
        "effective_date": rule.get("effective_date"), "end_date": rule.get("end_date"),
        "status": rule.get("status") or "enacted",
        "yields_to": [{"note": None, **y} for y in rule.get("yields_to") or []],
        "may_preempt": [{"note": None, **p} for p in rule.get("may_preempt") or []],
        "penalty": rule.get("penalty"), "quote": (rule.get("source") or {}).get("quote") or "",
        "confidence": rule.get("confidence") or 0.5,
    }


def review(rules: list[dict], docs: dict[str, dict], to_rule) -> list[dict]:
    """Return the reviewed rule list. ``to_rule(raw, doc)`` rebuilds an internal record."""
    out = []
    for r in rules:
        doc = docs.get((r.get("source") or {}).get("doc_id"))
        why = needs_review(r, doc["text"]) if (doc and r.get("kind", "rule") == "rule") else []
        if not why:
            out.append(r)
            continue
        user = (f"Flags: {'; '.join(why)}\n\nRecord:\n{json.dumps(_raw(r), indent=1)}\n\n"
                f"Document id: {doc['doc_id']}\n<document>\n{doc['text']}\n</document>")
        try:
            res = llm.complete_json(REVIEW_SYSTEM, user, REVIEW_SCHEMA, "review")
        except llm.LLMPending:
            from .extractor import PENDING
            PENDING.append(f"review:{r['rule_id']}")
            out.append(r)
            continue
        ledger.log("review", rule_id=r["rule_id"], flags=why, decision=res["decision"], reason=res["reason"],
                   model=config.LLM_MODEL)
        if res["decision"] == "drop":
            continue
        if res["decision"] == "keep":
            out.append({**r, "reviewed": {"decision": "keep", "flags": why}})
            continue
        new = to_rule(res["rule"], doc)
        if new:
            new["reviewed"] = {"decision": "correct", "flags": why, "reason": res["reason"]}
            out.append(new)
    return out
