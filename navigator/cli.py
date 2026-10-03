"""Command line: ``python -m navigator <command>``.

  inspect                 show what was found in the starter pack
  extract [--no-rule-pass off]   corpus -> out/rules.json (+ rules_internal.json)
  resolve [--offline]     addresses -> jurisdiction stacks (Census geocoder, cached)
  lookup [--as-of D] [--address ID]   -> out/lookups.json, or print one address
  changes                 -> out/changes.json (T1-T6 from config/change_cases.json)
  ingest FILE [--doc-id X] [--retrieval-date D] [--case T6]   add a new law and show what it changes
  site                    -> out/site (static demo)
  score [-- extra args]   run the official score.py from the starter pack
  all [--offline]         extract + resolve + lookup + changes + site
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import date

from . import config, export, site
from .audit import ledger
from .changes import tracker
from .extract import extractor
from .ingest.starter_pack import StarterPack, sha256_text
from .resolve import geocode

OUT = config.OUT_DIR
RULES_INTERNAL = OUT / "rules_internal.json"
ADDRS = OUT / "addresses_resolved.json"


def _load(p):
    if not p.exists():
        sys.exit(f"missing {p.name}; run the previous step first")
    return json.loads(p.read_text())


def cmd_inspect(a, sp: StarterPack):
    info = sp.describe()
    docs = sp.documents()
    info.update(documents=len(docs), link_only=sum(d["link_only"] for d in docs), addresses=len(sp.addresses()))
    print(json.dumps(info, indent=2))


def _write_rules(rules, sp: StarterPack) -> set[str]:
    """Write the official rules.json, validate each record, and return the exported team ids."""
    import jsonschema
    data, skipped = export.official_rules(rules, config.DEFAULT_AS_OF)
    schema = sp.schema()
    errors = []
    if schema:
        v = jsonschema.validators.validator_for(schema)(schema)
        for rec in data["rules"]:
            errors += [f"{rec['team_rule_id']}: {'/'.join(map(str, e.path))} {e.message}" for e in v.iter_errors(rec)]
    export.write_json(OUT / "rules.json", data)
    export.write_json(OUT / "schema_report.json", {"n_errors": len(errors), "errors": errors[:500],
                                                    "skipped": skipped})
    no_rule = [r for r in rules if r.get("kind") == "no_rule"]
    export.write_json(OUT / "no_rule_findings.json", no_rule)
    return {r["team_rule_id"] for r in data["rules"]}


def cmd_extract(a, sp: StarterPack):
    docs = sp.documents()
    rules = extractor.extract_corpus(docs, workers=a.workers, no_rule=not a.skip_no_rule)
    export.write_json(RULES_INTERNAL, rules)
    ids = _write_rules(rules, sp)
    rep = json.loads((OUT / "schema_report.json").read_text())
    print(f"{len(rules)} records ({sum(r.get('kind') == 'no_rule' for r in rules)} no-rule findings); "
          f"{len(ids)} exported, {len(rep['skipped'])} skipped, {rep['n_errors']} schema errors")


def cmd_resolve(a, sp: StarterPack):
    addrs = geocode.resolve_all(sp.addresses(), use_network=not a.offline)
    export.write_json(ADDRS, addrs)
    low = sum(1 for x in addrs if x["geocode"]["confidence"] == "low")
    print(f"{len(addrs)} addresses resolved ({low} low-confidence)")


def cmd_lookup(a, sp: StarterPack):
    rules, addrs = _load(RULES_INTERNAL), _load(ADDRS)
    as_of = date.fromisoformat(a.as_of) if a.as_of else config.DEFAULT_AS_OF
    if a.address:
        addrs = [x for x in addrs if x["address_id"] == a.address]
        print(json.dumps(export.lookups(addrs, rules, as_of), indent=1))
        return
    ids = _write_rules(rules, sp)
    data = export.official_lookups(addrs, rules, as_of, ids)
    name = "lookups.json" if as_of == config.DEFAULT_AS_OF else f"lookups_{as_of.isoformat()}.json"
    export.write_json(OUT / name, data)
    counts = {}
    for rows in data["lookups"].values():
        for r in rows:
            counts[r["result"]] = counts.get(r["result"], 0) + 1
    print(f"{name}: {len(data['lookups'])} addresses as of {as_of}: {counts}")


def cmd_changes(a, sp: StarterPack):
    rules, addrs = _load(RULES_INTERNAL), _load(ADDRS)
    data = tracker.run_all(rules, addrs, sp.change_cases())
    export.write_json(OUT / "changes_details.json", data)
    export.write_json(OUT / "changes.json", export.official_changes(data))
    for t in data["tests"]:
        print(f"{t['id']}: {len(t['affected_addresses'])} affected, {len(t['conflicts'])} conflict-flagged, "
              f"{len(t['rules'])} rules matched {('- ' + '; '.join(t['notes'])) if t['notes'] else ''}")


def cmd_ingest(a, sp: StarterPack):
    """Hour-16 path: add a document, extract it unaided, merge, and report what changed."""
    from pathlib import Path
    src = Path(a.file)
    text = src.read_text(encoding="utf-8", errors="replace")
    doc_id = a.doc_id or src.stem
    dest = sp.root / "ingested"
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, dest / f"{doc_id}.txt")
    doc = {"doc_id": doc_id, "title": a.title or src.stem, "url": a.url, "retrieval_date": a.retrieval_date,
           "jurisdiction_hint": None, "doc_type": "ingested", "text": text, "link_only": False,
           "sha256": sha256_text(text)}
    ledger.log("ingest", doc_id=doc_id, sha256=doc["sha256"], path=str(src))
    old = _load(RULES_INTERNAL)
    new = extractor.extract_document(doc)
    merged = extractor.consolidate([r for r in old if r.get("kind") == "rule"] + new)
    enacted = {(r["jurisdiction"]["id"], r["category"]) for r in merged if r.get("status") == "enacted"}
    dropped = [r for r in old if r.get("kind") == "no_rule" and (r["jurisdiction"]["id"], r["category"]) in enacted]
    merged += [r for r in old if r.get("kind") == "no_rule" and r not in dropped]
    for r in dropped:
        ledger.log("no_rule_withdrawn", rule_id=r["rule_id"], reason="new enacted rule in same jurisdiction/category")
    export.write_json(RULES_INTERNAL, merged)
    _write_rules(merged, sp)
    print(f"extracted {len(new)} rule(s) from {doc_id}:")
    for r in new:
        print(f"  - {r['citation']} | {r['jurisdiction']['id']} | {r['category']} | status={r['status']} "
              f"effective={r['effective_date']} | quote={'verified' if r['source']['quote'] else 'NOT VERIFIED'}")
    # register as a change case (T6 by default) and recompute
    cases_p = config.CONFIG_DIR / "change_cases.json"
    cases = json.loads(cases_p.read_text()) if cases_p.exists() else []
    case = next((c for c in cases if c["id"] == a.case), None)
    if case is None:
        case = {"id": a.case, "title": f"Ingested {doc_id}", "type": "in_force", "select": {}}
        cases.append(case)
    case["select"] = {**case.get("select", {}), "doc_id": doc_id}
    eff = sorted(d for d in (r.get("effective_date") for r in new) if d)
    case["before"] = config.DEFAULT_AS_OF.isoformat()
    case["after"] = eff[-1] if eff else config.DEFAULT_AS_OF.isoformat()
    cases_p.write_text(json.dumps(cases, indent=2))
    addrs = _load(ADDRS)
    result = tracker.run_case(case, merged, addrs)
    print(f"{case['id']}: {len(result['affected_addresses'])} affected address(es) as of {case['after']}; "
          f"before {case['before']} they were {'not yet covered' if eff and eff[-1] > case['before'] else 'covered'}")
    for aid in result["affected_addresses"][:20]:
        print("   ", aid)
    cmd_lookup(argparse.Namespace(as_of=None, address=None), sp)
    cmd_changes(a, sp)


def cmd_site(a, sp: StarterPack):
    rules, addrs = _load(RULES_INTERNAL), _load(ADDRS)
    p = OUT / "changes_details.json"
    changes = json.loads(p.read_text()) if p.exists() else None
    path = site.build(rules, addrs, changes)
    print(f"site written to {path}  (serve: python -m http.server -d {path} 8000)")


def cmd_score(a, sp: StarterPack):
    if not sp.score_script:
        sys.exit("score.py not found in the starter pack")
    args = [sys.executable, str(sp.score_script)] + (a.rest or [])
    print("$", " ".join(args))
    sys.exit(subprocess.call(args))


def cmd_all(a, sp: StarterPack):
    cmd_extract(a, sp)
    cmd_resolve(a, sp)
    cmd_lookup(argparse.Namespace(as_of=None, address=None), sp)
    cmd_changes(a, sp)
    cmd_site(a, sp)


def main(argv=None):
    p = argparse.ArgumentParser(prog="navigator", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--pack", help="starter pack directory (default data/starter_pack)")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("inspect", "extract", "resolve", "lookup", "changes", "ingest", "site", "score", "all"):
        s = sub.add_parser(name)
        if name in ("extract", "all"):
            s.add_argument("--workers", type=int, default=4)
            s.add_argument("--skip-no-rule", action="store_true")
        if name in ("resolve", "all"):
            s.add_argument("--offline", action="store_true", help="skip the Census geocoder")
        if name == "lookup":
            s.add_argument("--as-of")
            s.add_argument("--address")
        if name == "ingest":
            s.add_argument("file")
            s.add_argument("--doc-id")
            s.add_argument("--title")
            s.add_argument("--url")
            s.add_argument("--retrieval-date", default=date.today().isoformat())
            s.add_argument("--case", default="T6")
        if name == "score":
            s.add_argument("rest", nargs=argparse.REMAINDER)
    a = p.parse_args(argv)
    sp = StarterPack(a.pack)
    globals()[f"cmd_{a.cmd}"](a, sp)


if __name__ == "__main__":
    main()
