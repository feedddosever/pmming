# Video scripts

The scores must be on screen. No `score.py` is publicly available (confirmed by the organizers), so the
self-check scorecard is shown instead. Before recording, run this and keep the terminal visible for a few seconds:
```bash
NAV_LLM=agent python -m navigator all      # offline replay of the committed run (seconds)
NAV_LLM=agent python -m navigator report   # 10/10 self-check scorecard
python -m http.server -d out/site 8000     # demo UI at http://localhost:8000
```
Say "informational only, not legal advice" once in every video. The UI shows it on every view.

## 1. Team video (max 1 min)
- Names and roles: team lead / pipeline, extraction and review, geocoding and coverage logic, UI and video.
- The problem in one sentence: renters and operators can't tell which of dozens of overlapping state and city
  rules apply to one building on one date.
- Our angle: **unknown beats wrong**. Every answer quotes the law word for word, and when the data can't
  decide, we say so instead of guessing.

## 2. Demo video (max 1 min)
Recorded version: 47 s, captioned (San Francisco, Hoboken with the as-of date, Spanish, Boston, Law changes,
Live extraction replay). Berkeley, Jersey City and the 2025-12-31 check are optional extras if time allows.
Use these addresses from the official sample (`#A0016` etc. in the URL also works):

| Step | Address | What to point at |
|---|---|---|
| 1 | A0016, 3515 Fillmore St, San Francisco (1926, 21 units) | SF just-cause **applies**; the state just-cause rule is **superseded** because the state law yields to it. Open the quote and retrieval date. Rent caps are **unknown**: the corpus never states SF's 1979 cutoff, and we say so |
| 2 | A0005, 1609 Addison St, Berkeley (no year, no units) | missing facts give **unknown**, with the explanation naming the missing fact; Berkeley 13.63 is **pending** (first reading only) |
| 3 | A0002, 1031-1035 Clinton St, Hoboken | Hoboken algorithmic-pricing ban **applies**; NJ FAIR Act is **not yet effective** and carries the **conflict flag** |
| 4 | A0008, 1065 Summit Ave, Jersey City | the Jersey City ban applies here, the Hoboken one doesn't (T2 boundary) |
| 5 | A0006, 69-71 Westland Ave, Boston | MA bills S.2983 / H.5222 are **pending**, never in force; no city rent cap (c.40P bar) |

Then:
1. Switch to **Español**: same results, Spanish explanations.
2. Move the date to **2027-07-02**: the FAIR Act flips to applies on the NJ addresses.
3. Move it back to **2025-12-31**: the CA AB 325 / SB 763 rules show not yet effective (T1).
4. Scroll to the **Changes** section: T1–T5 with the affected address counts (250 / 90 / 140 / 110 / 0).

## 3. Technical video (max 1 min)
Recorded version: 58 s, eight screens (pipeline, extraction, citation lock, coverage, as-of engine, scorecard,
audit log and scalability).
1. **Pipeline** (README "Architecture" diagram): starter pack → extraction (strict JSON schema) → review of risky
   records → clause normalization → evidence-gated "no rule" checks → Census geocoding → as-of engine → outputs.
2. **Citation lock**: `navigator/extract/verify.py`; every `quoted_span` is a verbatim substring
   of its source (scorecard line 2: 58/58). Records that fail are skipped, never exported.
3. **Three-valued logic**: show `navigator/apply/predicates.py`; a boundary-year building returns unknown, a
   20-unit building is never "single-family owner exempt" even when the owner type is unknown.
4. **As-of engine and precedence**: status comes from enacted / effective / pending / struck dates;
   `superseded` only from the rule's own "yields to" text; conflicts only from preemption language.
5. **Scorecard**: `python -m navigator report`, 10/10, T1–T5 against `dev/change_tests.json`. The organizers
   confirmed no `score.py` is publicly available, so say that this self-check stands in for it.
6. **Hour-16 drill**: `python -m navigator ingest <new ordinance> --doc-id hour16 --retrieval-date <date>`; show the
   affected addresses and the effective date it prints, then the new rule in the UI. Without agent help, use the
   site's **Live extraction** tab with your own API key: paste the ordinance (or fetch its official page with a
   Bright Data key), extract, and show the verified quote and the affected sample addresses. Say why the tab asks
   for keys: there weren't enough promo codes for API credits.
7. **Responsible design**: `out/audit_log.jsonl` (source hashes, model, prompt version, every review decision),
   the honest limits list in the README.

## Model access note (say it in the technical video)
There weren't enough promo codes for API credits, so the team had no API key and the model steps ran in agent mode: each request, with the
same prompt and schema as the API path, was answered by a Claude Code agent. The answers are committed and
schema-checked, so anyone can replay the run offline. With a key, the default mode makes the same calls itself.
