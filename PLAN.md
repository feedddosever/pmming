# Rental Housing Law Navigator: Build Plan (team lead)

Target: Challenge 02 (RealPage × Hack-Nation). 100 points, of which **75 are auto-scored**:
extraction 25, address coverage 20, citations 15, change tracking 15. Judges score the
other 25: plain language 10, responsible design 10, scalability 5.

## 0. Constraints that shape the design
| Constraint (from the brief) | Design response |
|---|---|
| Automated extraction only; hour-16 ordinance and a live rerun in the demo | One command `nav ingest <file>` re-extracts, re-resolves and diffs. No hand-written rules anywhere in the repo |
| Starter-pack formats (schema, CSV columns) are only known at kickoff | `ingest/starter_pack.py` auto-detects columns. One `exporter` maps our internal model to the provided JSON Schema and validates against it |
| Missing an applicable rule costs 2×; "unknown" earns partial credit | Tri-state predicate engine. "does not apply" is returned **only** when a known fact excludes the rule; missing facts → `unknown` |
| Citation points need a quoted span found in the corpus | Citation lock: every quote is verified verbatim against the source. If it isn't found, snap to the closest exact substring, otherwise drop the rule and log it |
| 19 "no rule at this level" findings in the key | Explicit pass over every jurisdiction × category pair that emits `no_rule` findings with evidence |
| Effective dates, pending bills, struck ballot measures | Status/as-of engine: every rule carries `status` + `effective_date` (+ `end_date`) |
| Local rules override state rules | Precedence pass: when a same-category local rule covers the address, the state rule is marked `superseded` (if the extracted rule says it yields) |
| T3 conflict flag | Conflict detector: state rule vs local rule in the same category with overlapping effect windows → `conflict` flag |
| "Not legal advice"; cite source + retrieval date; audit log | UI banner on every view; every answer carries citation, quote and retrieval date; JSONL audit ledger with SHA-256 of sources and model I/O |
| No network for some services at demo time | Every external call (LLM, geocoder) is cached to disk; reruns are deterministic from the cache |

## 1. Architecture
```
navigator/
  models.py            internal Pydantic models (Rule, Coverage, Address, LookupResult, ChangeResult)
  config.py            paths + model settings via env vars
  ingest/starter_pack.py   load corpus manifest + docs, addresses CSV, schema, dev key (column auto-detect)
  extract/
    llm.py             provider abstraction: openai | anthropic | replay (cache-only) | fake (tests)
    prompts.py         extraction + no-rule prompts (schema-constrained JSON)
    chunking.py        section-aware chunking with character offsets
    extractor.py       doc → candidate rules (two independent passes)
    verify.py          citation lock (verbatim quote verification / snapping)
    consolidate.py     dedupe, pass agreement → confidence, no-rule findings
  resolve/
    geocode.py         Census batch geocoder client + disk cache + offline fallback
    jurisdictions.py   canonical jurisdiction ids, stack (state > county > city), SF city-county
  apply/
    predicates.py      coverage DSL, tri-state evaluation
    status.py          as-of engine (enacted/pending/struck/superseded/not yet effective)
    engine.py          address × rules → results, precedence, conflicts
  changes/tracker.py   change cases → affected addresses, before/after, conflict flags
  audit/ledger.py      append-only JSONL ledger
  export.py            internal → rules.json / lookups.json / changes.json (+ schema validation)
  score/local_score.py approximate scorer; wraps the official score.py when present
  cli.py               nav extract | resolve | lookup | changes | ingest | score | all | serve
  web/app.py           FastAPI JSON API
  web/static/index.html  renter view (EN/ES), as-of slider, citations, flags, audit
tests/                 unit tests for predicates, status, verify, engine, changes, export, pipeline (fake LLM)
fixtures/              SYNTHETIC test fixtures only (clearly labelled, not legal text)
data/starter_pack/     ← drop the official starter pack here (git-ignored)
out/                   generated rules.json / lookups.json / changes.json
```

## 2. Data model (internal)
`Rule`: id, category (6 enums), jurisdiction {level, state, county, city, id}, title,
requirement (plain-language), key_value (e.g. "5% + CPI, max 10%"), coverage (structured
predicates + raw text), exemptions (structured + raw), effective_date, end_date, status
(enacted | pending | struck), overrides / yields_to, penalty, citation, source_doc_id,
quote, quote_start/end, retrieval_date, confidence, extraction_passes, flags.

Coverage DSL (all fields optional; AND of clauses; each clause tri-state):
`year_built {lte|gte|lt|gt}`, `units {gte|lte}`, `use_codes {in|not_in}`,
`owner_type {in|not_in}`, `building_type {in|not_in}`, `certificate_of_occupancy_before`,
plus `requires_unknown_fact: [..]` for facts never present in the data → `unknown`.

Lookup result per (address, rule): applies | unknown | superseded | not_yet_effective |
pending | not_applicable (not exported). Each result carries a reason chain + citation.

## 3. Schedule (24 h, team of 4)
| Hour | Extraction lead | Address/coverage lead | Change/time lead | UI + video lead |
|---|---|---|---|---|
| 0–1 | Map starter-pack schema → exporter; run official scorer on empty output | Batch-geocode all ~500 addresses (cache) | Read change cases + participant guide partial-credit rules | Repo, README skeleton, UI shell |
| 1–6 | Extraction v1 over all 87 docs (pass A) | Jurisdiction stacks + predicates | Status/as-of engine, precedence | Renter view wired to API |
| 6–8 | **First dev score**. Error dashboard | idem | idem | idem |
| 8–16 | Pass B + agreement; no-rule pass; quote lock; prompt fixes per error class | Unknown policy tuning on dev key | T1–T5 + conflict flags; `nav ingest` rehearsal with a self-written ordinance | Spanish, audit view, flags |
| 16–20 | Hour-16 ordinance through `nav ingest` (record it) | Re-run lookups | T6 + as-of queries | Record demo pieces |
| 20–23 | Freeze; final official score | | | 3 videos with scores, README, deploy |

## 4. Definition of done
- `nav all` regenerates `out/rules.json`, `out/lookups.json` and `out/changes.json` from the
  starter pack with no manual edits; output validates against the provided schema.
- `nav ingest new_ordinance.txt` re-runs extraction and prints affected addresses.
- Official `score.py` dev score shown in the README and the videos.
- Every UI answer shows citation, quote, retrieval date, "as of" date, status badge and the "not legal advice" banner.
- Tests green (`pytest`).

## 5. What I build now vs. at kickoff
Now: the whole system, tests, synthetic fixtures, approximate scorer and UI. Fixture rules
are produced by the same extraction pipeline, run against a fake LLM in tests.
At kickoff (needs the starter pack, API key and network): map the schema (≈30 min),
geocode, run the real extraction, and switch the scorer to the official `score.py`.

## 6. Audit (independent review) and resulting changes
An adversarial review of this plan against the brief found 13 issues. Changes adopted:

| # | Finding | Change |
|---|---|---|
| 1 | The conflict check, run on the as-of date, misses T3 (the FAIR Act starts 7/1/2027) and fires falsely for CA (AB 325 is layered on top of the local bans) | Raise conflicts **only** from extracted `may_preempt` text, independent of the as-of date. Flag the affected local-ban addresses |
| 2 | "Local overrides state" is too broad | Both rules apply by default. `superseded` only when the rule has an extracted `yields_to` clause **and** the local rule `applies`. If the local rule is `unknown`, the state rule becomes `unknown` |
| 3 | Rule granularity drives matching | One record per (jurisdiction, category, primary citation). Normalize citation style. Calibrate on the dev key in hour 1 |
| 4 | The "no rule" pass would over-generate (78 pairs vs 19) | Emit `no_rule` only when a verbatim quote supports it (preemption, struck measure, pending-only) |
| 5 | As-of semantics | Default as-of pinned to 2026-10-01 (configurable). Pending is never `applies`. Struck is never exported as in force. `end_date` supports version chains |
| 6 | The condition format was too weak | Added `age_years` (relative to as-of), `before_date` (certificate-of-occupancy proxy, boundary year → unknown), exemption groups (OR of ANDs), and three-valued logic so known facts resolve owner-type exemptions |
| 7 | Jurisdiction traps | Census place (CA) / county subdivision (NJ, MA), never the postal city. SF is a single city-county node. Offline alias fallback marked low-confidence |
| 8 | changes.json under-specified | Change cases are config-driven: before/after dates, affected addresses, before/after rule sets, flags. T6 flows through `nav ingest` |
| 9 | Scoring asymmetry | `unknown` only when a needed fact is missing. Absence from lookups = not applicable |
| 10 | Fuzzy quote snapping is risky | Verbatim only (whitespace-normalized). Fall back to the longest verbatim sentence fragment, otherwise flag `needs_review`. Link-only docs are never quoted |
| 11 | Submission items | Static site (no server) so the live link can be deployed early. `out/*.json` committed. Video checklist in README |
| 12 | Over-scoping | Approximate scorer dropped (wrap the official `score.py` only). Single extraction pass, second pass optional. One LLM provider (Anthropic) + replay cache. Loose dict models |
| 13 | Santa Ana / missing facts / use codes | Santa Ana rules extracted with no lookups. Berkeley/San Diego missing facts → `unknown`. Use-code tables configurable |
