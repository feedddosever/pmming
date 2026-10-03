# Rental Housing Law Navigator

Hack-Nation × RealPage, Challenge 02. Given any sample apartment address, it shows which
rental-housing rules apply **as of a date**, explains them in plain English and Spanish with the
exact quoted source text, and shows which addresses a new, pending or struck law changes.

> Informational only. **Not legal advice.** Every interface and output file says so.

## How it maps to the scoring
| Points | What earns them here |
|---|---|
| Extraction 25 | LLM extraction with a strict JSON schema; one record per (jurisdiction, category, provision); citation normalization; evidence-gated "no rule at this level" findings |
| Address coverage 20 | Census place / county-subdivision resolution (never the postal city); three-valued coverage logic that returns **unknown** instead of guessing (missing an applicable rule costs 2×) |
| Citations 15 | Citation lock: every exported quote is a verbatim substring of the corpus document, or the rule is flagged for review |
| Change tracking 15 | As-of engine (enacted / pending / struck / not yet effective) + config-driven change cases T1–T6 + extracted-preemption conflict flags (T3) |
| Plain language 10 | Static renter view, English/Spanish, quote + retrieval date on every answer, "as of" date picker |
| Responsible design 10 | Unknown/low-confidence/needs-review flags, append-only audit log (source hashes, model, prompt version, raw outputs), no legal-advice framing |
| Scalability 5 | New city = drop documents + one entry in `navigator/resolve/jurisdictions.py`; `nav ingest` adds laws live |

## Quick start
```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...            # extraction model: NAV_MODEL (default claude-opus-5-5)
# the official starter pack goes anywhere under data/starter_pack/ (found automatically)
python -m navigator inspect             # what was found: 87 docs (54 with text), 500 addresses, schema, T1-T5
python -m navigator all                 # extract → resolve → lookup → changes → site
python -m navigator lookup --as-of 2027-07-02   # extra as-of snapshots (lookups_<date>.json)
python -m http.server -d out/site 8000  # demo UI
pytest -q                               # 13 tests, run offline with a fake LLM on synthetic fixtures
```
Outputs, in the participant guide's formats (§5):
- `out/rules.json`: `{"rules": [...]}`, each record validated against `schema/rule_record.schema.json`
  (`team_rule_id` is a stable hash, so ids survive reruns and `nav ingest`). Rules whose quote cannot be
  verified verbatim are skipped and listed in `out/schema_report.json`, never exported with an invented span.
- `out/lookups.json`: `{"as_of", "lookups": {address_id: [{team_rule_id, result, explanation, conflict_flag}]}}`
  for all 500 addresses; rules that don't apply are left out.
- `out/changes.json`: `{test_id: {affected_address_ids, conflict_flag_address_ids, notes}}` for T1–T5
  (dates and types read from `dev/change_tests.json`; selectors in `config/change_cases.json`).
- Also `changes_details.json` (before/after per address), `no_rule_findings.json`, `audit_log.jsonl`, and
  `out/site/` (static demo for GitHub Pages or any static host).

The official pack has **no scoring script or dev answer key** ("no-scoring" edition), so quality is checked
against the expected behaviour stated in `dev/change_tests.json` and the participant guide.

Every LLM and geocoder response is cached in `cache/`. `NAV_LLM=replay` reruns the whole pipeline
offline and deterministically (useful for the live rerun in the demo check).

## Run checklist
1. `export ANTHROPIC_API_KEY=...`, then `python -m navigator all`.
2. Read `out/schema_report.json`: skipped rules (unverified quotes) and any schema errors.
3. Spot-check the known cases: SF before/after 1979 (superseded vs unknown), Berkeley/San Diego (unknown),
   Hoboken/Jersey City (local bans, FAIR Act conflict flag), Boston/Cambridge (pending bills, no rent cap).
4. Check `out/changes.json` against the expected behaviour in `dev/change_tests.json` (T1–T5).
5. If citations or rule granularity look off, adjust `navigator/extract/prompts.py`, bump `PROMPT_VERSION`
   and rerun (unchanged calls come from the cache).
6. `python -m navigator lookup --as-of 2027-07-02` for the T3 "after" snapshot shown in the demo.

## Hour-16 drill
```bash
python -m navigator ingest path/to/cambridge_ordinance.txt --doc-id hour16 --retrieval-date 2026-10-04
```
This extracts the new document unaided, merges it, recomputes lookups and changes, registers it as
T6 (`--case`), and prints the affected addresses and the effective date. Rehearse with
`fixtures/new_cambridge_ordinance.txt` before hour 16, then record the real run for the video.

## Videos (scores must be on screen)
- **Team:** who we are, roles.
- **Demo:** pick an SF address built before 1979 (local ordinance applies, state cap superseded), one built
  in 1979 (unknown, with the explanation), Berkeley/San Diego (missing facts → unknown), Hoboken
  (local ban + FAIR Act conflict flag, not yet effective), Boston (pending bills, no city rent control).
  Then switch to Spanish, move the date to 2027-07-02, and open the Changes tab.
- **Technical:** pipeline diagram, citation lock, three-valued logic, as-of engine, T1–T5 results against
  the expected behaviour in `dev/change_tests.json`, and a `nav ingest` run of a new ordinance.

## Architecture
```
starter pack ─► ingest/starter_pack.py ─► extract/extractor.py ──(LLM, cached)──► rules_internal.json ─► rules.json
                 (format auto-detect)      ├─ verify.py: verbatim citation lock
                                           └─ evidence-gated no-rule pass
addresses ─► resolve/geocode.py (Census, cached; offline alias fallback) ─► jurisdiction stacks
rules + stacks + date ─► apply/predicates.py (three-valued) + status.py (as-of) + engine.py (precedence, conflicts)
                      ─► lookups.json · changes/tracker.py ─► changes.json · site.py ─► static UI
```

## Design decisions (from the plan audit, see PLAN.md §6)
- **Unknown beats wrong.** A rule is dropped only when a *known* fact excludes it. Missing facts
  (San Diego year built, Berkeley units, owner type) give `unknown`. Three-valued logic still lets known
  facts decide (a 20-unit building is never the "single-family owner" exemption).
- **Precedence comes from the text.** `superseded` only when the rule itself yields to a local rule that
  applies (e.g. the state cap yields to SF rent control). If that local rule is `unknown`, so is the state rule.
- **Conflicts come from preemption language**, independent of the as-of date, so T3 is flagged before 2027.
- **Pending is never in force; struck is never exported**; not-yet-effective rules are labelled as such.
- **Dates:** default as-of is 2026-10-01 (`NAV_AS_OF`), never the system clock. Age tests are relative to
  the as-of date; boundary years return `unknown`.

## Status and limits
- Adapted to the official starter pack (formats, column names, category names, T1–T5).
- Address resolution has been run on all 500 sample addresses: 493 matched by the Census geocoder,
  7 resolved from the postal city (house-number-less Boston streets, Newark rows with wrong ZIPs);
  every address lands in the expected city.
- **Extraction has not been run yet:** it needs `ANTHROPIC_API_KEY`. Estimated 55 extraction calls,
  roughly $10–20 with the default model.
- Tests use a synthetic fixture corpus under `fixtures/` (labelled *not legal text*) and a fake LLM.
