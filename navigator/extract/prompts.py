"""Prompts and JSON schemas for extraction. Changing anything here should bump PROMPT_VERSION."""
from __future__ import annotations

from .. import config

FACTS = ["year_built", "age_years", "units", "use_code", "building_type", "owner_type",
         "owner_units_owned", "subsidized", "other"]
OPS = ["lt", "lte", "gt", "gte", "eq", "ne", "in", "not_in", "before_date", "is_true", "is_false"]
LEVELS = ["state", "county", "city"]

_nullable_str = {"type": ["string", "null"]}
_clause = {
    "type": "object",
    "properties": {
        "fact": {"type": "string", "enum": FACTS},
        "op": {"type": "string", "enum": OPS},
        "value_number": {"type": ["number", "null"]},
        "value_text": _nullable_str,
        "value_list": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["fact", "op", "value_number", "value_text", "value_list"],
    "additionalProperties": False,
}
_ref = {
    "type": "object",
    "properties": {"category": {"type": "string", "enum": config.CATEGORIES},
                   "level": {"type": "string", "enum": LEVELS},
                   "note": _nullable_str},
    "required": ["category", "level", "note"],
    "additionalProperties": False,
}
RULE_PROPS = {
    "category": {"type": "string", "enum": config.CATEGORIES},
    "jurisdiction_level": {"type": "string", "enum": LEVELS},
    "jurisdiction_state": {"type": "string"},
    "jurisdiction_name": {"type": "string"},
    "title": {"type": "string"},
    "citation": {"type": "string"},
    "requirement": {"type": "string"},
    "requirement_es": {"type": "string"},
    "key_value": _nullable_str,
    "coverage_text": {"type": "string"},
    "applies_if": {"type": "array", "items": _clause},
    "exemptions": {"type": "array", "items": {
        "type": "object",
        "properties": {"label": {"type": "string"}, "all": {"type": "array", "items": _clause}},
        "required": ["label", "all"], "additionalProperties": False}},
    "effective_date": _nullable_str,
    "end_date": _nullable_str,
    "status": {"type": "string", "enum": ["enacted", "pending", "struck"]},
    "yields_to": {"type": "array", "items": _ref},
    "may_preempt": {"type": "array", "items": _ref},
    "penalty": _nullable_str,
    "quote": {"type": "string"},
    "confidence": {"type": "number"},
}
RULES_SCHEMA = {
    "type": "object",
    "properties": {"rules": {"type": "array", "items": {
        "type": "object", "properties": RULE_PROPS, "required": list(RULE_PROPS), "additionalProperties": False}}},
    "required": ["rules"],
    "additionalProperties": False,
}

NO_RULE_PROPS = {
    "exists": {"type": "boolean"},
    "explanation": {"type": "string"},
    "citation": _nullable_str,
    "quote": _nullable_str,
}
NO_RULE_SCHEMA = {
    "type": "object", "properties": NO_RULE_PROPS, "required": list(NO_RULE_PROPS), "additionalProperties": False,
}

CATEGORY_GUIDE = """Categories:
- rent_increase_limits: caps on rent increases (formula, covered buildings, exemptions, local vs state precedence).
- just_cause_eviction: limits on evictions to listed causes, notice, relocation assistance.
- security_deposits: maximum deposit, exceptions (e.g. small landlords), effective date.
- application_screening_fees: caps on application/screening fees, allowed upfront charges, receipts, refunds.
- screening_restrictions: limits on criminal-history or source-of-income screening, timing rules.
- algorithmic_rent_setting: bans/limits on software or algorithms that set or recommend rents (definition of covered software, prohibited conduct, penalties)."""

EXTRACT_SYSTEM = f"""You extract structured rental-housing rules from official legal text for a public, citation-backed lookup tool. Output is checked automatically against the source, so precision matters more than recall of minor details.

{CATEGORY_GUIDE}

Granularity: emit ONE record per (jurisdiction, category, primary legal provision). Do not split one provision into sub-records; do not merge provisions from different jurisdictions. Ignore definitions sections, findings and procedural rules unless they ARE the rule. Skip material outside the six categories.

Field rules:
- citation: the primary provision in standard short form, e.g. "Cal. Civ. Code § 1947.12", "S.F. Admin. Code ch. 37", "N.J.S.A. 2A:18-61.1", "M.G.L. c.186 § 15B", "Berkeley Mun. Code ch. 13.63". If this document is a bill, cite the bill (e.g. "AB 325 (2025)").
- quote: copy ONE contiguous passage VERBATIM from the document (character for character, 1-3 sentences) that states the core requirement. Never paraphrase, never join separate passages, never add ellipses.
- status: enacted (signed/adopted law, even if its effective date is in the future), pending (bill or proposal not enacted), struck (removed from the ballot, invalidated, failed or repealed). A struck measure is still recorded (it will be reported as failed) so users can see it is not law.
- Jurisdiction: state rules use the state; city rules use the city. San Francisco is a consolidated city and county: use level city, name "San Francisco".
- effective_date / end_date: ISO YYYY-MM-DD when the text states them; null otherwise. Never guess.
- requirement: one or two plain-English sentences a renter can understand (reading level ~8th grade). requirement_es: the same in Spanish.
- key_value: the headline number or formula ("5% + CPI, max 10%", "one month's rent", "$50, CPI-adjusted") or null.
- applies_if (all must hold) and exemptions (each group is an AND; the rule does not apply if ANY group holds) use facts:
  year_built (integer year), age_years (building age on the lookup date; use for rolling tests like "built within the last 15 years" -> exemption age_years lte 15), units (number of units in the building), use_code, building_type (single_family, condo, duplex, multifamily, mobile_home, dormitory...), owner_type (natural_person, corporation, reit, public...), owner_units_owned, subsidized.
  Certificate-of-occupancy cutoffs (e.g. "on or before June 13, 1979"): use fact year_built, op before_date, value_text = the day AFTER the last covered date when the text says "on or before" (1979-06-14), or the cutoff date itself when it says "before". The data only has year built, so the boundary year is resolved as unknown automatically.
  Only encode conditions the text states. If a condition depends on a fact not in this list, use fact "other" with value_text describing it.
- yields_to: when this rule says it does not apply where a stricter/local ordinance applies (e.g. a state rent cap exempting units under local rent control), list {{category, level}} of the rule it yields to.
- may_preempt: when this rule states or the text indicates it may preempt or conflict with local rules, list {{category, level, note}}.
- confidence: 0-1, your confidence that every field is correct.
Return {{"rules": []}} if the document contains no rule in scope."""


def extract_user(doc: dict, chunk_text: str, part: str) -> str:
    return (f"Document id: {doc['doc_id']}\nTitle: {doc.get('title')}\nURL: {doc.get('url')}\n"
            f"Jurisdiction hint: {doc.get('jurisdiction_hint')}\nPart: {part}\n\n<document>\n{chunk_text}\n</document>")


NO_RULE_SYSTEM = f"""You check whether official legal text shows that NO rule of a given category exists at a given jurisdiction level (for example: state law prohibits local rent control; a local measure was struck from the ballot; only pending, unenacted bills exist).

{CATEGORY_GUIDE}

Answer exists=true ONLY when the excerpts explicitly support the absence of a rule at that level, and copy one supporting passage VERBATIM into quote with its citation. Otherwise answer exists=false with quote=null and citation=null. Never infer absence merely from silence."""


def no_rule_user(jurisdiction_label: str, level: str, category: str, excerpts: list[tuple[str, str]]) -> str:
    body = "\n\n".join(f"<excerpt doc=\"{d}\">\n{t}\n</excerpt>" for d, t in excerpts)
    return (f"Question: is there evidence that there is NO {category} rule at the {level} level for "
            f"{jurisdiction_label}?\n\n{body}")
