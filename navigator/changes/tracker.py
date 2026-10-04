"""Change tracking: which addresses does a new, pending, struck or newly effective law affect?

Change cases live in ``config/change_cases.json`` (selectors are data, not code), so the hour-16
ordinance only needs a new entry, or ``nav ingest`` adds one automatically.

Case types:
* ``in_force``  - compare results at ``before`` and ``after``; affected = addresses where a selected
                  rule applies/unknown at ``after`` (T1, T2, T3, T6)
* ``pending``   - bills that are not law: reported as pending, never in force; affected = addresses
                  they *would* cover if enacted (T4)
* ``struck``    - removed measures: affected set is empty by definition (T5)
"""
from __future__ import annotations

import json
import re
from datetime import date

from .. import config
from ..apply.engine import evaluate_address

ACTIVE = ("applies", "unknown")


_TYPE_MAP = {"as_of": "in_force", "boundary": "in_force", "pending": "pending", "negative": "struck"}


def load_cases(official=None) -> list[dict]:
    """Official tests (dev/change_tests.json) supply ids, types and dates; config supplies selectors.

    Official ``rule_ids`` (e.g. "CA-ALG-01") name the organizers' answer-key rules, which our
    extracted records cannot know, so each test is matched to our rules through a selector."""
    p = config.CONFIG_DIR / "change_cases.json"
    ours = {c["id"]: c for c in (json.loads(p.read_text()) if p.exists() else [])}
    items = official if isinstance(official, list) else (official or {}).get("tests") or []
    cases = []
    for o in items:
        if not isinstance(o, dict):
            continue
        tid = str(o.get("test_id") or o.get("id"))
        c = dict(ours.pop(tid, {"id": tid, "select": {}}))
        c["id"], c["title"] = tid, o.get("title") or c.get("title")
        c["type"] = _TYPE_MAP.get(o.get("type"), c.get("type", "in_force"))
        if o.get("as_of_before"):
            c["before"] = o["as_of_before"]
        if o.get("as_of_after") or o.get("as_of"):
            c["after"] = o.get("as_of_after") or o.get("as_of")
        c["official"] = o
        cases.append(c)
    return cases + list(ours.values())  # cases we added ourselves (e.g. via nav ingest)


def select(rules: list[dict], sel: dict) -> list[dict]:
    out = []
    for r in rules:
        if r.get("kind", "rule") != "rule":
            continue
        jid = r["jurisdiction"]["id"]
        if sel.get("category") and r["category"] != sel["category"]:
            continue
        if sel.get("jurisdiction_prefix") and not jid.startswith(sel["jurisdiction_prefix"]):
            continue
        if sel.get("jurisdiction_ids") and jid not in sel["jurisdiction_ids"]:
            continue
        if sel.get("status") and r.get("status") != sel["status"]:
            continue
        if sel.get("doc_id") and sel["doc_id"] not in ([(r.get("source") or {}).get("doc_id")] + (r.get("sources_seen") or [])):
            continue
        if sel.get("citation_regex"):
            hay = " ".join(str(x) for x in (r.get("citation"), r.get("title"), (r.get("source") or {}).get("title")))
            if not re.search(sel["citation_regex"], hay, re.I):
                continue
        out.append(r)
    return out


def _short(results):
    return [{"rule_id": x["rule_id"], "result": x["result"], "citation": x["citation"]} for x in results]


def run_case(case: dict, rules: list[dict], addresses: list[dict]) -> dict:
    target = select(rules, case.get("select", {}))
    ids = {r["rule_id"] for r in target}
    ctype = case.get("type", "in_force")
    after = date.fromisoformat(case.get("after") or config.DEFAULT_AS_OF.isoformat())
    before = date.fromisoformat(case["before"]) if case.get("before") else None
    res = {"id": case["id"], "title": case.get("title"), "type": ctype,
           "before": before.isoformat() if before else None, "after": after.isoformat(),
           "rules": [{"rule_id": r["rule_id"], "citation": r["citation"], "status": r.get("status"),
                      "effective_date": r.get("effective_date")} for r in target],
           "affected_addresses": [], "details": {}, "conflicts": [], "notes": []}
    if not target:
        res["notes"].append("no extracted rule matched this case's selector; check extraction or selector")
    if ctype == "struck":
        res["notes"].append("measure is not law; no address is affected")
        return res

    effs = [date.fromisoformat(r["effective_date"]) for r in target if r.get("effective_date")]
    horizon = max([after] + effs)
    for a in addresses:
        if ctype == "pending":
            now = [x for x in evaluate_address(a, rules, after) if x["rule_id"] in ids]
            if_enacted = [x for x in evaluate_address(a, rules, horizon, assume_enacted=ids)
                          if x["rule_id"] in ids and x["result"] in ACTIVE]
            if if_enacted:
                res["affected_addresses"].append(a["address_id"])
                res["details"][a["address_id"]] = {"now": _short(now), "if_enacted": _short(if_enacted)}
            continue
        aft = evaluate_address(a, rules, after)
        hit = [x for x in aft if x["rule_id"] in ids and x["result"] in ACTIVE]
        if not hit:
            continue
        res["affected_addresses"].append(a["address_id"])
        det = {"after": _short(aft)}
        if before:
            det["before"] = _short(evaluate_address(a, rules, before))
        flags = [f for x in hit for f in x["flags"] if f.get("type") == "conflict"]
        # Conflicts are about the selected rule meeting a local rule, whatever the date.
        for x in evaluate_address(a, rules, horizon):
            if x["rule_id"] in ids:
                flags += [f for f in x["flags"] if f.get("type") == "conflict"]
        wants_conflicts = "conflict_with" in (case.get("official") or {}) or not case.get("official")
        if flags and wants_conflicts:
            uniq = {json.dumps(f, sort_keys=True): f for f in flags}
            det["conflict_flags"] = list(uniq.values())
            res["conflicts"].append(a["address_id"])
        res["details"][a["address_id"]] = det
    if ctype == "pending":
        res["notes"].append("pending bills are reported as pending and never as in force")
    return res


def run_all(rules, addresses, official=None) -> dict:
    cases = load_cases(official)
    return {"generated_for_as_of": config.DEFAULT_AS_OF.isoformat(),
            "tests": [run_case(c, rules, addresses) for c in cases]}
