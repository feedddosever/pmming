"""Write submission files and map internal rules onto the provided JSON Schema."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import jsonschema

from . import config
from .apply.engine import evaluate_address, no_rule_findings

# target field name (lower) -> function(rule) -> value
def _exemptions_text(r):
    return [e.get("label") for e in (r.get("coverage") or {}).get("exemptions") or []]


FIELD_SOURCES = {
    "id": lambda r: r["rule_id"], "rule_id": lambda r: r["rule_id"],
    "kind": lambda r: r.get("kind"), "finding_type": lambda r: r.get("kind"),
    "category": lambda r: r["category"],
    "jurisdiction": lambda r: r["jurisdiction"]["label"], "jurisdiction_id": lambda r: r["jurisdiction"]["id"],
    "jurisdiction_level": lambda r: r["jurisdiction"]["level"], "level": lambda r: r["jurisdiction"]["level"],
    "jurisdiction_name": lambda r: r["jurisdiction"]["label"],
    "state": lambda r: r["jurisdiction"]["id"].split(":")[0],
    "title": lambda r: r.get("title"), "name": lambda r: r.get("title"),
    "requirement": lambda r: r.get("requirement"), "summary": lambda r: r.get("requirement"),
    "plain_language": lambda r: r.get("requirement"), "plain_language_summary": lambda r: r.get("requirement"),
    "key_value": lambda r: r.get("key_value"), "value": lambda r: r.get("key_value"),
    "coverage": lambda r: (r.get("coverage") or {}).get("text"),
    "coverage_conditions": lambda r: (r.get("coverage") or {}).get("text"),
    "exemptions": _exemptions_text,
    "effective_date": lambda r: r.get("effective_date"), "end_date": lambda r: r.get("end_date"),
    "status": lambda r: r.get("status"), "penalty": lambda r: r.get("penalty"),
    "citation": lambda r: r.get("citation"), "source_citation": lambda r: r.get("citation"),
    "quote": lambda r: r["source"].get("quote"), "quoted_span": lambda r: r["source"].get("quote"),
    "source_quote": lambda r: r["source"].get("quote"), "quoted_text": lambda r: r["source"].get("quote"),
    "source_url": lambda r: r["source"].get("url"), "url": lambda r: r["source"].get("url"),
    "source_doc_id": lambda r: r["source"].get("doc_id"), "doc_id": lambda r: r["source"].get("doc_id"),
    "source_document": lambda r: r["source"].get("doc_id"), "document_id": lambda r: r["source"].get("doc_id"),
    "retrieval_date": lambda r: r["source"].get("retrieval_date"),
    "confidence": lambda r: r.get("confidence"),
}


def _item_schema(schema: dict | None):
    if not schema:
        return None
    if schema.get("type") == "array":
        return schema.get("items")
    props = schema.get("properties") or {}
    if "rules" in props and props["rules"].get("type") == "array":
        return props["rules"].get("items")
    return schema


def _coerce(value, prop: dict):
    t = prop.get("type")
    types = t if isinstance(t, list) else [t]
    if value is None:
        return None if (not t or "null" in types) else ("" if "string" in types else value)
    if "array" in types and not isinstance(value, list):
        return [value]
    if "string" in types and isinstance(value, list):
        return "; ".join(str(v) for v in value if v)
    if "string" in types and not isinstance(value, str) and "number" not in types:
        return str(value)
    return value


def map_rule(r: dict, item_schema: dict | None, overrides: dict) -> dict:
    if not item_schema or not item_schema.get("properties"):
        return {k: v for k, v in r.items() if k != "provenance"}
    out = {}
    for name, prop in item_schema["properties"].items():
        if name in overrides:
            val = r
            for part in overrides[name].split("."):
                val = val.get(part) if isinstance(val, dict) else None
        else:
            fn = FIELD_SOURCES.get(name.lower())
            val = fn(r) if fn else None
        if prop.get("enum") and val not in prop["enum"]:
            alt = {str(e).lower().replace(" ", "_").replace("-", "_"): e for e in prop["enum"]}
            val = alt.get(str(val).lower().replace(" ", "_").replace("-", "_"), val)
        out[name] = _coerce(val, prop)
    return out


def export_rules(rules: list[dict], schema: dict | None) -> tuple[list[dict], list[str]]:
    p = config.CONFIG_DIR / "schema_map.json"
    overrides = json.loads(p.read_text()) if p.exists() else {}
    item = _item_schema(schema)
    mapped = [map_rule(r, item, overrides) for r in rules]
    errors = []
    if item:
        v = jsonschema.validators.validator_for(item)(item)
        for i, m in enumerate(mapped):
            for e in v.iter_errors(m):
                errors.append(f"{rules[i]['rule_id']}: {'/'.join(map(str, e.path))} {e.message}")
    return mapped, errors


def lookups(addresses: list[dict], rules: list[dict], as_of: date) -> dict:
    return {
        "as_of": as_of.isoformat(),
        "disclaimer": "Informational only. Not legal advice.",
        "addresses": [{
            "address_id": a["address_id"],
            "address": ", ".join(x for x in [a.get("street"), a.get("city"), a.get("state"), a.get("zip")] if x),
            "jurisdictions": a.get("stack"),
            "geocode": a.get("geocode"),
            "results": evaluate_address(a, rules, as_of),
            "no_rule_findings": no_rule_findings(a, rules),
        } for a in addresses],
    }


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False))
