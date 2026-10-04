"""Self-check scorecard (the starter pack ships no scoring script).

Checks the submission files against the official schema, the corpus (verbatim quotes), the
participant-guide formats, and the expected behaviour written in dev/change_tests.json.
"""
from __future__ import annotations

import collections
import json

import jsonschema

from . import config
from .extract.verify import locate


def _addresses():
    return {a["address_id"]: a for a in json.loads((config.OUT_DIR / "addresses_resolved.json").read_text())}


def _city(a):
    return a["stack"][-1]


def run(sp) -> list[tuple[str, bool, str]]:
    out = config.OUT_DIR
    rules = json.loads((out / "rules.json").read_text())["rules"]
    lookups = json.loads((out / "lookups.json").read_text())
    changes = json.loads((out / "changes.json").read_text())
    addrs = _addresses()
    by_id = {r["team_rule_id"]: r for r in rules}
    docs = {d["doc_id"]: d["text"] for d in sp.documents()}
    checks = []

    schema = sp.schema()
    v = jsonschema.validators.validator_for(schema)(schema)
    bad = [r["team_rule_id"] for r in rules if any(True for _ in v.iter_errors(r))]
    checks.append(("rules.json: every record valid against rule_record.schema.json", not bad,
                   f"{len(rules) - len(bad)}/{len(rules)} valid"))
    unq = [r["team_rule_id"] for r in rules if not locate(r["quoted_span"], docs.get(r["source_doc_id"], ""))]
    checks.append(("rules.json: every quoted_span found verbatim in its source document", not unq,
                   f"{len(rules) - len(unq)}/{len(rules)} verified"))
    missing = set(addrs) - set(lookups["lookups"])
    rows = [x for rs in lookups["lookups"].values() for x in rs]
    keys_ok = all(set(x) == {"team_rule_id", "result", "explanation", "conflict_flag"} for x in rows)
    dangling = [x for x in rows if x["team_rule_id"] not in by_id]
    checks.append(("lookups.json: all addresses, guide row format, ids resolve to rules",
                   not missing and keys_ok and not dangling,
                   f"{len(lookups['lookups'])} addresses, {len(rows)} results "
                   f"{dict(collections.Counter(x['result'] for x in rows))}"))

    tests = {t["test_id"]: t for t in sp.change_cases() or []}
    st = lambda s: {k for k, a in addrs.items() if a["state"] == s}  # noqa: E731
    city = lambda c: {k for k, a in addrs.items() if _city(a).endswith(":" + c)}  # noqa: E731
    exp = {
        "T1": (st("CA"), set()),
        "T2": (city("hoboken") | city("jersey-city"), set()),
        "T3": (st("NJ"), city("hoboken") | city("jersey-city")),
        "T4": (st("MA"), set()),
        "T5": (set(), set()),
    }
    for tid, (aff, conf) in exp.items():
        got = changes.get(tid, {})
        ga, gc = set(got.get("affected_address_ids", [])), set(got.get("conflict_flag_address_ids", []))
        ok = ga == aff and gc == conf
        title = tests.get(tid, {}).get("title", "")
        checks.append((f"{tid} {title}", ok, f"affected {len(ga)}/{len(aff)} expected, conflict flags {len(gc)}/{len(conf)}"))

    # T2 boundary: each local ban only inside its own city; none in Newark.
    t2_rules = {tid: r for tid, r in by_id.items() if r["category"] == "algorithmic_rent_setting" and r["level"] == "city"}
    leak = []
    for aid, rs in lookups["lookups"].items():
        for x in rs:
            r = t2_rules.get(x["team_rule_id"])
            if r and r["jurisdiction"].split(",")[0].lower().replace(" ", "-") not in _city(addrs[aid]):
                leak.append(aid)
    checks.append(("T2 boundary: local algorithmic bans never applied outside their own city", not leak,
                   f"{len(leak)} leaks"))
    # T5: no rent cap reported for Boston or Cambridge (the c.40P bar on local rent control is not a cap).
    ma_caps = [x for aid, rs in lookups["lookups"].items() if addrs[aid]["state"] == "MA" for x in rs
               if by_id[x["team_rule_id"]]["category"] == "rent_increase_limits"
               and "40P" not in by_id[x["team_rule_id"]]["citation"]]
    checks.append(("T5: no rent cap reported in Boston or Cambridge", not ma_caps, f"{len(ma_caps)} cap results"))
    return checks


def print_report(sp):
    checks = run(sp)
    width = max(len(c[0]) for c in checks)
    passed = sum(ok for _, ok, _ in checks)
    print(f"Self-check scorecard (as of {config.DEFAULT_AS_OF}) — not legal advice\n")
    for name, ok, detail in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name.ljust(width)}  {detail}")
    print(f"\n{passed}/{len(checks)} checks passed")
    return passed == len(checks)
