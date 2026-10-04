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


# ---------------- official submission formats (participant guide §5) ----------------
import hashlib  # noqa: E402

from .apply import status as _st  # noqa: E402
from .resolve.jurisdictions import CITIES  # noqa: E402


def team_id(rule_id: str) -> str:
    """Stable short id: survives reruns and ingests (no renumbering)."""
    return "r-" + hashlib.sha1(rule_id.encode()).hexdigest()[:8]


def _official_jurisdiction(jid: str) -> tuple[str, str]:
    parts = jid.split(":")
    if len(parts) == 1:
        return jid, "state"
    st, _lvl, s = parts
    name = CITIES[(st, s)][1] if (st, s) in CITIES else s.replace("-", " ").title()
    return f"{name}, {st}", "city"


def _official_status(r: dict, as_of: date) -> str | None:
    s = _st.status_on(r, as_of)
    return {"in_force": "in_force", "not_yet_effective": "not_yet_effective", "pending": "pending",
            "struck": "failed"}.get(s)  # expired versions are not exported


def official_rules(rules: list[dict], as_of: date) -> tuple[dict, list[dict]]:
    """Returns ({"rules": [...]}, skipped). Rules without a verified quote are skipped, never invented."""
    real = [r for r in rules if r.get("kind", "rule") == "rule"]
    out, skipped = [], []
    for r in real:
        status = _official_status(r, as_of)
        quote = (r.get("source") or {}).get("quote")
        if status is None or not quote or len(quote) < 20:
            skipped.append({"rule_id": r["rule_id"], "reason": "expired version" if status is None else "no verified quote"})
            continue
        juris, level = _official_jurisdiction(r["jurisdiction"]["id"])
        overrides, notes = [], []
        state = r["jurisdiction"]["id"].split(":")[0]
        for y in r.get("yields_to") or []:
            cat, lvl = y.get("category") or r["category"], y.get("level") or "city"
            locals_ = [o for o in real if o is not r and o["category"] == cat
                       and o["jurisdiction"]["id"].startswith(f"{state}:{lvl}:")
                       and _official_status(o, as_of) in ("in_force", "not_yet_effective", "pending")
                       and len((o.get("source") or {}).get("quote") or "") >= 20]
            new = [team_id(o["rule_id"]) for o in locals_ if team_id(o["rule_id"]) not in overrides]
            overrides += new
            note = f"yields to local {cat} rules where they apply"
            if locals_ and note not in notes:
                notes.append(note)
        conflict_notes = [p.get("note") or "possible preemption of local rules" for p in r.get("may_preempt") or []]
        # a local rule targeted by a state preemption clause carries the flag too
        for o in real:
            for p in o.get("may_preempt") or []:
                if (o is not r and p.get("category") == r["category"] and level == "city"
                        and o["jurisdiction"]["id"] == r["jurisdiction"]["id"].split(":")[0]):
                    conflict_notes.append(f"may be preempted by {o.get('citation')}")
                    overrides.append(team_id(o["rule_id"]))
        cov = r.get("coverage") or {}
        out.append({
            "team_rule_id": team_id(r["rule_id"]),
            "jurisdiction": juris,
            "level": level,
            "category": r["category"],
            "status": status,
            "title": r.get("title") or r.get("citation"),
            "requirement": r.get("requirement") or "",
            "key_value": r.get("key_value"),
            "coverage_conditions": {"text": cov.get("text"), "applies_if": cov.get("applies_if") or [],
                                    "exemptions": cov.get("exemptions") or []},
            "exemptions": "; ".join(e.get("label", "") for e in cov.get("exemptions") or []) or None,
            "overrides": sorted(set(overrides)),
            "interaction": "; ".join(notes) or None,
            "effective_date": r.get("effective_date"),
            "citation": r.get("citation") or "",
            "source_doc_id": (r.get("source") or {}).get("doc_id"),
            "source_url": (r.get("source") or {}).get("url") or "",
            "quoted_span": quote,
            "confidence": r.get("confidence"),
            "conflict_flag": bool(conflict_notes),
            "conflict_note": "; ".join(conflict_notes) or None,
            # extra, schema-compatible fields used by the UI
            "requirement_es": r.get("requirement_es"),
            "retrieval_date": (r.get("source") or {}).get("retrieval_date"),
        })
    return {"rules": out}, skipped


_RESULT_WORDS = {"applies": "Applies", "unknown": "Unknown", "superseded": "Superseded",
                 "not_yet_effective": "Not yet effective", "pending": "Pending (not law)"}


def official_lookups(addresses: list[dict], rules: list[dict], as_of: date, exported_ids: set[str]) -> dict:
    by_id = {r["rule_id"]: r for r in rules}
    out = {}
    for a in addresses:
        rows = []
        for x in evaluate_address(a, rules, as_of):
            tid = team_id(x["rule_id"])
            if tid not in exported_ids:
                continue
            r = by_id[x["rule_id"]]
            why = list(x["reasons"])
            if x.get("superseded_by"):
                why.append(f"governed by {by_id[x['superseded_by']].get('citation')}")
            if x["result"] == "not_yet_effective":
                why.append(f"effective {r.get('effective_date')}")
            if x["result"] == "pending":
                why.append("bill or proposal, not enacted")
            conflicts = [f for f in x["flags"] if f.get("type") == "conflict"]
            if conflicts:
                why.append("possible conflict with " + ", ".join(by_id[f["with"]].get("citation", "") for f in conflicts if f["with"] in by_id))
            expl = f"{_RESULT_WORDS[x['result']]}: {r.get('citation')} ({_official_jurisdiction(r['jurisdiction']['id'])[0]})"
            if why:
                expl += ". " + "; ".join(why)
            rows.append({"team_rule_id": tid, "result": x["result"], "explanation": expl + ".",
                         "conflict_flag": bool(conflicts)})
        out[a["address_id"]] = rows
    return {"as_of": as_of.isoformat(), "lookups": out}


def official_changes(change_results: dict) -> dict:
    out = {}
    for t in change_results["tests"]:
        notes = list(t["notes"])
        if t["rules"]:
            notes.insert(0, "rules: " + "; ".join(f"{r['citation']} ({r['status']})" for r in t["rules"]))
        if t.get("before"):
            notes.append(f"compared as of {t['before']} and {t['after']}")
        out[t["id"]] = {"affected_address_ids": sorted(t["affected_addresses"]),
                        "conflict_flag_address_ids": sorted(t["conflicts"]),
                        "notes": " | ".join(notes)}
    return out
