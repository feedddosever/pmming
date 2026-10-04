"""Build a static, server-free demo site (deployable to GitHub Pages / any static host).

Results only change on dates where some rule's status changes, so evaluating the engine on every
boundary date (plus Jan 1 of each year, for building-age tests) gives the exact answer for any
"as of" date in range. The UI snaps the slider to the latest precomputed date <= the chosen date.
"""
from __future__ import annotations

import json
import shutil
from datetime import date

from . import config
from .apply.engine import evaluate_address, no_rule_findings
from .apply.status import boundary_dates
from .extract import prompts
from .extract.extractor import CHUNK_CHARS
from .resolve.jurisdictions import CITIES, STATES, label

RESULT_CODES = ["applies", "unknown", "superseded", "not_yet_effective", "pending"]


def timeline_dates(rules) -> list[date]:
    ds = set(boundary_dates(rules)) | {config.DEFAULT_AS_OF}
    ds |= {date(y, 1, 1) for y in range(2019, 2031)}
    return sorted(d for d in ds if date(2019, 1, 1) <= d <= date(2031, 1, 1))


def live_payload(docs: list[dict]) -> dict:
    """Everything the in-browser "live extraction" panel needs: the same prompt and schema as the
    pipeline, the corpus texts, and the jurisdiction ids used by the address stacks."""
    juris = {st: {disp.lower(): f"{st}:city:{slug}" for (cst, slug), (_c, disp, _n) in CITIES.items() if cst == st}
             for st in STATES}
    return {
        "system": prompts.EXTRACT_SYSTEM, "schema": prompts.RULES_SCHEMA,
        "prompt_version": config.PROMPT_VERSION, "effort": config.LLM_EFFORT, "max_chars": CHUNK_CHARS,
        "jurisdictions": juris,
        "docs": [{k: d.get(k) for k in ("doc_id", "title", "url", "retrieval_date", "jurisdiction_hint", "text")}
                 for d in docs if not d.get("link_only")],
    }


def build(rules: list[dict], addresses: list[dict], changes: dict | None = None, docs: list[dict] | None = None):
    site = config.OUT_DIR / "site"
    if site.exists():
        shutil.rmtree(site)
    shutil.copytree(config.ROOT / "web", site)
    exported = [r for r in rules if r.get("kind", "rule") == "rule"]
    rule_index = {r["rule_id"]: i for i, r in enumerate(exported)}
    reasons: dict[str, int] = {}

    def rid(text):
        return reasons.setdefault(text, len(reasons))

    dates = timeline_dates(rules)
    results = []
    for a in addresses:
        per_date = []
        for d in dates:
            row = []
            for x in evaluate_address(a, rules, d):
                row.append([rule_index[x["rule_id"]], RESULT_CODES.index(x["result"]),
                            [rid(t) for t in x["reasons"]],
                            [rule_index.get(f.get("with"), -1) for f in x["flags"] if f.get("type") == "conflict"]])
            per_date.append(row)
        results.append(per_date)

    payload = {
        "as_of_default": config.DEFAULT_AS_OF.isoformat(),
        "dates": [d.isoformat() for d in dates],
        "result_codes": RESULT_CODES,
        "categories": {k: list(v) for k, v in config.CATEGORY_LABELS.items()},
        "rules": [{
            "id": r["rule_id"], "category": r["category"], "jurisdiction": r["jurisdiction"]["label"],
            "title": r.get("title"), "requirement": r.get("requirement"), "requirement_es": r.get("requirement_es"),
            "key_value": r.get("key_value"), "citation": r.get("citation"), "status": r.get("status"),
            "effective_date": r.get("effective_date"), "confidence": r.get("confidence"),
            "flags": r.get("flags") or [], "coverage_text": (r.get("coverage") or {}).get("text"),
            "source": {k: (r.get("source") or {}).get(k) for k in ("doc_id", "url", "title", "retrieval_date", "quote", "sha256")},
            "provenance": r.get("provenance"),
        } for r in exported],
        "no_rule": [{"id": r["rule_id"], "category": r["category"], "jurisdiction": label(r["jurisdiction"]["id"]),
                     "explanation": r.get("requirement"), "citation": r.get("citation"),
                     "quote": (r.get("source") or {}).get("quote")} for r in rules if r.get("kind") == "no_rule"],
        "reasons": list(reasons),
        "addresses": [{"id": a["address_id"],
                       "label": ", ".join(x for x in [a.get("street"), a.get("city"), a.get("state"), a.get("zip")] if x),
                       "facts": {k: a["facts"].get(k) for k in ("year_built", "units", "use_code", "units_min", "units_max", "use_description")},
                       "stack": a.get("stack"), "stack_labels": [label(j) for j in a.get("stack") or []], "geocode": a.get("geocode"),
                       "no_rule": [f["rule_id"] for f in no_rule_findings(a, rules)]} for a in addresses],
        "results": results,
        "changes": changes,
    }
    (site / "data.json").write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False))
    if docs is not None:
        (site / "live.json").write_text(json.dumps(live_payload(docs), separators=(",", ":"), ensure_ascii=False))
    return site
