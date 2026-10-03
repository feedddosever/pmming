"""Corpus -> rule records. Fully automated: no rule is ever written by hand."""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

from .. import config
from ..audit import ledger
from ..resolve.jurisdictions import CITIES, STATES, canonical_id, label
from . import llm, prompts
from .verify import lock_quote

CHUNK_CHARS = 120_000
OVERLAP = 4_000


def chunks(text: str):
    if len(text) <= CHUNK_CHARS:
        yield 0, text, "1/1"
        return
    n = (len(text) - OVERLAP) // (CHUNK_CHARS - OVERLAP) + 1
    for i in range(n):
        start = i * (CHUNK_CHARS - OVERLAP)
        yield start, text[start:start + CHUNK_CHARS], f"{i + 1}/{n}"


def norm_citation(c: str | None) -> str:
    c = (c or "").replace("Section", "§").replace("sec.", "§").replace("Sec.", "§")
    c = re.sub(r"§\s*", "§", c)
    return re.sub(r"\s+", " ", c).strip()


def _cit_key(c: str) -> str:
    return re.sub(r"[^a-z0-9§]", "", norm_citation(c).lower())


def _rule_from_llm(raw: dict, doc: dict) -> dict | None:
    jid = canonical_id(raw["jurisdiction_level"], raw["jurisdiction_state"], raw["jurisdiction_name"])
    if not jid:
        return None
    lock = lock_quote(raw.get("quote"), doc["text"])
    flags = [] if lock["verified"] else ["needs_review:quote_not_found"]
    cit = norm_citation(raw.get("citation"))
    rid = f"{jid}|{raw['category']}|{_cit_key(cit)}"
    return {
        "rule_id": rid,
        "kind": "rule",
        "category": raw["category"],
        "jurisdiction": {"id": jid, "level": "state" if ":" not in jid else jid.split(":")[1], "label": label(jid)},
        "title": raw.get("title"),
        "citation": cit,
        "requirement": raw.get("requirement"),
        "requirement_es": raw.get("requirement_es"),
        "key_value": raw.get("key_value"),
        "coverage": {"applies_if": raw.get("applies_if") or [], "exemptions": raw.get("exemptions") or [],
                     "text": raw.get("coverage_text")},
        "effective_date": _iso(raw.get("effective_date")),
        "end_date": _iso(raw.get("end_date")),
        "status": raw.get("status") or "enacted",
        "yields_to": raw.get("yields_to") or [],
        "may_preempt": raw.get("may_preempt") or [],
        "penalty": raw.get("penalty"),
        "confidence": round(float(raw.get("confidence") or 0.5) * (1.0 if lock["verified"] else 0.6), 3),
        "flags": flags,
        "source": {"doc_id": doc["doc_id"], "url": doc.get("url"), "title": doc.get("title"),
                   "retrieval_date": doc.get("retrieval_date"), "sha256": doc["sha256"],
                   "quote": lock["quote"], "quote_start": lock["start"], "quote_end": lock["end"],
                   "quote_method": lock["method"]},
        "provenance": {"model": config.LLM_MODEL, "prompt_version": config.PROMPT_VERSION},
    }


def _iso(s):
    if not s:
        return None
    m = re.match(r"^\d{4}-\d{2}-\d{2}", str(s))
    return m.group(0) if m else None


def extract_document(doc: dict) -> list[dict]:
    if doc.get("link_only"):
        ledger.log("skip_link_only", doc_id=doc["doc_id"])
        return []
    rules = []
    for offset, text, part in chunks(doc["text"]):
        out = llm.complete_json(prompts.EXTRACT_SYSTEM, prompts.extract_user(doc, text, part),
                                prompts.RULES_SCHEMA, "rules")
        for raw in out.get("rules", []):
            r = _rule_from_llm(raw, doc)
            if r:
                rules.append(r)
        ledger.log("extract", doc_id=doc["doc_id"], part=part, sha256=doc["sha256"], n_rules=len(out.get("rules", [])),
                   model=config.LLM_MODEL, prompt_version=config.PROMPT_VERSION, output=out)
    return rules


def consolidate(rules: list[dict]) -> list[dict]:
    """One record per (jurisdiction, category, citation); keep the best-verified, most confident one."""
    best: dict[str, dict] = {}
    for r in rules:
        cur = best.get(r["rule_id"])
        score = (r["source"]["quote_method"] == "verbatim", r["source"]["quote"] is not None, r["confidence"])
        if cur is None:
            best[r["rule_id"]] = {**r, "_score": score, "sources_seen": [r["source"]["doc_id"]]}
        else:
            cur["sources_seen"] = sorted(set(cur["sources_seen"] + [r["source"]["doc_id"]]))
            if score > cur["_score"]:
                seen = cur["sources_seen"]
                best[r["rule_id"]] = {**r, "_score": score, "sources_seen": seen}
    out = []
    for r in best.values():
        r.pop("_score", None)
        out.append(r)
    return sorted(out, key=lambda r: r["rule_id"])


# ---------------- "no rule at this level" findings ----------------
_CAT_WORDS = {
    "rent_increase": ["rent control", "rent increase", "rent stabilization", "rent cap", "amount of rent", "rental rate"],
    "just_cause_eviction": ["just cause", "eviction", "good cause"],
    "security_deposit": ["security deposit", "deposit"],
    "application_screening_fee": ["application fee", "screening fee", "broker", "fee"],
    "screening_restriction": ["criminal", "source of income", "fair chance", "screening"],
    "algorithmic_rent_setting": ["algorithm", "software", "pricing", "coordinat"],
}


def _excerpts(docs, state: str, place_words: list[str], category: str, limit: int = 6, width: int = 1500):
    hits = []
    for d in docs:
        if d.get("link_only"):
            continue
        t, low = d["text"], d["text"].lower()
        if not any(w in low for w in place_words):
            continue
        for w in _CAT_WORDS[category]:
            for m in re.finditer(re.escape(w), low):
                s = max(0, m.start() - width // 2)
                hits.append((d["doc_id"], t[s:s + width]))
                break
    seen, out = set(), []
    for h in hits:
        if h[0] not in seen:
            seen.add(h[0])
            out.append(h)
    return out[:limit]


def no_rule_pass(rules: list[dict], docs: list[dict]) -> list[dict]:
    """Ask, for every in-scope city x category with no city rule, whether the corpus shows absence."""
    # A pair is "covered" only by an enacted rule; pending/struck-only pairs still get checked.
    have = {(r["jurisdiction"]["id"], r["category"]) for r in rules
            if r.get("kind") == "rule" and r.get("status") == "enacted"}
    tasks = []
    targets = [(st, None, STATES[st]) for st in STATES] + [(st, c, v[1]) for (st, c), v in CITIES.items()]
    for st, city, disp in targets:
        jid = f"{st}:city:{city}" if city else st
        level = "city" if city else "state"
        for cat in config.CATEGORIES:
            if (jid, cat) in have:
                continue
            ex = _excerpts(docs, st, [disp.lower(), STATES[st].lower()], cat)
            if ex:
                tasks.append((jid, level, cat, ex))

    def run(t):
        jid, level, cat, ex = t
        out = llm.complete_json(prompts.NO_RULE_SYSTEM, prompts.no_rule_user(label(jid), level, cat, ex),
                                prompts.NO_RULE_SCHEMA, "no_rule")
        ledger.log("no_rule_check", jurisdiction=jid, category=cat, output=out)
        if not out.get("exists") or not out.get("quote"):
            return None
        for doc_id, _ in ex:
            doc = next(d for d in docs if d["doc_id"] == doc_id)
            lock = lock_quote(out["quote"], doc["text"])
            if lock["verified"]:
                return {
                    "rule_id": f"{jid}|{cat}|no_rule", "kind": "no_rule", "category": cat,
                    "jurisdiction": {"id": jid, "level": level, "label": label(jid)},
                    "title": f"No {cat.replace('_', ' ')} rule at the {level} level",
                    "citation": norm_citation(out.get("citation")), "requirement": out["explanation"],
                    "status": "enacted", "effective_date": None, "end_date": None, "confidence": 0.7, "flags": [],
                    "source": {"doc_id": doc_id, "url": doc.get("url"), "retrieval_date": doc.get("retrieval_date"),
                               "sha256": doc["sha256"], "quote": lock["quote"], "quote_start": lock["start"],
                               "quote_end": lock["end"], "quote_method": lock["method"]},
                    "provenance": {"model": config.LLM_MODEL, "prompt_version": config.PROMPT_VERSION},
                }
        return None  # unverifiable evidence -> emit nothing

    with ThreadPoolExecutor(4) as ex:
        return [f for f in ex.map(run, tasks) if f]


def extract_corpus(docs: list[dict], workers: int = 4, no_rule: bool = True) -> list[dict]:
    with ThreadPoolExecutor(workers) as ex:
        all_rules = [r for rs in ex.map(extract_document, docs) for r in rs]
    rules = consolidate(all_rules)
    if no_rule:
        rules += no_rule_pass(rules, docs)
    return rules

