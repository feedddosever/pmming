"""Turn free-text coverage clauses into testable ones (model-driven, then evaluated by code).

First-pass extraction stores conditions the address data cannot test as free text (fact "other",
or owner/building wording). Each such rule is sent once, with its clauses, to the model, which maps
every clause to a fixed vocabulary:

  building_type   compared with the derived building type (config/use_codes.json)
  subsidized      deed-restricted / subsidized / affordable-housing status
  owner_occupied  owner lives on site (not in the data: stays unknown)
  units           a unit-count test the text implies (e.g. "duplex" -> units lte 2)
  trigger         a tenancy or event condition (tenant tenure, eviction type, notice served):
                  it says WHEN the rule operates for a tenancy, not WHETHER the building is covered
  covered_by      "unit is covered by the local <category> ordinance": resolved from that
                  ordinance's own coverage for the same address
  unknown         a building fact the data genuinely lacks
"""
from __future__ import annotations

import json

from ..audit import ledger
from . import llm, prompts

DATA_FACTS = {"year_built", "age_years", "units", "use_code"}
BUILDING_TYPES = ["multifamily", "single_family", "condominium", "duplex", "cooperative", "tenancy_in_common",
                  "senior_housing", "dormitory", "hotel_motel", "mobilehome", "care_facility", "shelter",
                  "owner_occupied_room"]
KINDS = ["building_type", "subsidized", "owner_occupied", "units", "trigger", "covered_by", "unknown"]

_item = {
    "type": "object",
    "properties": {
        "index": {"type": "integer"},
        "kind": {"type": "string", "enum": KINDS},
        "op": {"type": "string", "enum": prompts.OPS},
        "value_number": {"type": ["number", "null"]},
        "value_text": {"type": ["string", "null"]},
        "value_list": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["index", "kind", "op", "value_number", "value_text", "value_list"],
    "additionalProperties": False,
}
NORMALIZE_SCHEMA = {"type": "object", "properties": {"clauses": {"type": "array", "items": _item}},
                    "required": ["clauses"], "additionalProperties": False}

NORMALIZE_SYSTEM = f"""You convert coverage conditions of one housing-law rule into a fixed, testable form.
Lookups are per BUILDING (an apartment address), using these data: year built, unit count, assessor use
code and a derived building type (one of {", ".join(BUILDING_TYPES)}).

For every numbered clause, return one item with the same index and a kind:
- building_type: the clause is about the kind of building. Use op "in" or "not_in" with value_list from the
  allowed building types (e.g. "single-family home" -> in [single_family]; "condominium or townhome" ->
  in [condominium]; "dormitory" -> in [dormitory]; "hotel or motel" -> in [hotel_motel]; "mobilehome" ->
  in [mobilehome]; "hospital, care or treatment facility" -> in [care_facility]).
- subsidized: deed-restricted, subsidized, income-restricted or government-assisted housing. op is_true
  (clause requires that status) or is_false.
- owner_occupied: the owner lives in the building. op is_true or is_false.
- units: the clause implies a unit count (e.g. "duplex" -> op lte, value_number 2; "three or more units" ->
  op gte, value_number 3). Prefer combining with owner_occupied by returning the units test only when the
  clause is purely about size.
- trigger: a condition about the tenancy or an event, not the building (tenant has lived there N months,
  type of eviction, notice served, primary residence of the tenant, lease expired). These say when the
  rule operates for a tenancy. Use op is_true.
- covered_by: the clause says the unit must be (or must not be) covered by a local ordinance of a category,
  e.g. "unit is subject to the city's Rent Stabilization Ordinance" -> op is_true, value_text
  "rent_increase_limits"; "unit is not regulated by the RSO" -> op is_false, value_text "rent_increase_limits".
  value_text must be one of: {", ".join(prompts.config.CATEGORIES)}.
- unknown: any other building fact the data cannot show. Use op is_true.
Keep the clause's direction: a clause that must hold for the rule to apply, or a clause inside an exemption,
keeps its meaning; only translate it."""


def _clauses(rule: dict):
    cov = rule.get("coverage") or {}
    out = []
    for i, c in enumerate(cov.get("applies_if") or []):
        if c["fact"] not in DATA_FACTS:
            out.append(("applies_if", None, i, c))
    for e_i, ex in enumerate(cov.get("exemptions") or []):
        for i, c in enumerate(ex.get("all") or []):
            if c["fact"] not in DATA_FACTS:
                out.append(("exemption", e_i, i, c))
    return out


def normalize(rules: list[dict]) -> list[dict]:
    out = []
    for r in rules:
        todo = _clauses(r) if r.get("kind", "rule") == "rule" else []
        if not todo:
            out.append(r)
            continue
        cov = r.get("coverage") or {}
        lines = []
        for n, (where, e_i, i, c) in enumerate(todo):
            label = "applies only if" if where == "applies_if" else \
                f"exemption '{cov['exemptions'][e_i].get('label')}' requires"
            val = c.get("value_text") or c.get("value_list") or c.get("value_number")
            lines.append(f"{n}. [{label}] fact={c['fact']} op={c['op']} value={json.dumps(val)}")
        user = (f"Rule: {r.get('citation')} ({r['category']}, {r['jurisdiction']['id']})\n"
                f"Coverage text: {cov.get('text')}\n\nClauses:\n" + "\n".join(lines))
        try:
            res = llm.complete_json(NORMALIZE_SYSTEM, user, NORMALIZE_SCHEMA, "normalize")
        except llm.LLMPending:
            from .extractor import PENDING
            PENDING.append(f"normalize:{r['rule_id']}")
            out.append(r)
            continue
        new_cov = json.loads(json.dumps(cov))
        by_n = {it["index"]: it for it in res["clauses"]}
        for n, (where, e_i, i, c) in enumerate(todo):
            it = by_n.get(n)
            if not it:
                continue
            fact = {"building_type": "building_type", "subsidized": "subsidized", "owner_occupied": "owner_occupied",
                    "units": "units", "trigger": "trigger", "covered_by": "covered_by", "unknown": "other"}[it["kind"]]
            clause = {"fact": fact, "op": it["op"], "value_number": it["value_number"],
                      "value_text": it["value_text"] if fact != "other" else (c.get("value_text") or it["value_text"]),
                      "value_list": it["value_list"], "source_text": c.get("value_text")}
            if where == "applies_if":
                new_cov["applies_if"][i] = clause
            else:
                new_cov["exemptions"][e_i]["all"][i] = clause
        ledger.log("normalize", rule_id=r["rule_id"], before=cov, after=new_cov)
        out.append({**r, "coverage": new_cov, "normalized": True})
    return out
