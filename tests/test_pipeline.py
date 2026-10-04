import json
from datetime import date

from navigator import cli, config
from navigator.apply.engine import evaluate_address


def run_all(ws):
    cli.main(["--pack", str(ws / "pack"), "all", "--offline", "--workers", "2"])
    out = ws / "out"
    return (json.loads((out / "rules_internal.json").read_text()),
            json.loads((out / "addresses_resolved.json").read_text()), out)


def results(addrs, rules, aid, as_of=date(2026, 10, 1)):
    a = next(x for x in addrs if x["address_id"] == aid)
    return {r["rule_id"].split("|")[0] + "|" + r["category"]: r for r in evaluate_address(a, rules, as_of)}


def test_end_to_end(workspace):
    rules, addrs, out = run_all(workspace)
    # citation lock: invented quote dropped, mis-spaced quote repaired to the exact source span
    ballot = next(r for r in rules if "Ballot" in r["citation"])
    assert ballot["source"]["quote"] is None and "needs_review:quote_not_found" in ballot["flags"]
    fair = next(r for r in rules if "FAIR" in r["citation"])
    assert fair["source"]["quote_method"] == "verbatim" and "No landlord shall use" in fair["source"]["quote"]
    # schema mapping validates against the (fixture) schema
    assert json.loads((out / "schema_report.json").read_text())["n_errors"] == 0
    # no-rule findings only with evidence: Boston and Cambridge rent control
    nr = {r["rule_id"] for r in rules if r["kind"] == "no_rule"}
    assert nr == {"MA:city:boston|rent_increase_limits|no_rule", "MA:city:cambridge|rent_increase_limits|no_rule"}

    sf1 = results(addrs, rules, "SF1")        # 1962: local ordinance applies, state cap yields
    assert sf1["CA:city:san-francisco|rent_increase_limits"]["result"] == "applies"
    assert sf1["CA|rent_increase_limits"]["result"] == "superseded"
    sf2 = results(addrs, rules, "SF2")        # built 1979: local coverage unknown -> state unknown
    assert sf2["CA:city:san-francisco|rent_increase_limits"]["result"] == "unknown"
    assert sf2["CA|rent_increase_limits"]["result"] == "unknown"
    sf3 = results(addrs, rules, "SF3")        # 2018: state 15-year exemption, local not covered
    assert "CA|rent_increase_limits" not in sf3 and "CA:city:san-francisco|rent_increase_limits" not in sf3
    sd1 = results(addrs, rules, "SD1")        # no year built -> unknown, never "does not apply"
    assert sd1["CA|rent_increase_limits"]["result"] == "unknown"
    hb1 = results(addrs, rules, "HB1")
    assert hb1["NJ|algorithmic_rent_setting"]["result"] == "not_yet_effective"
    assert hb1["NJ:city:hoboken|algorithmic_rent_setting"]["flags"][0]["type"] == "conflict"
    bo1 = results(addrs, rules, "BO1")
    assert bo1["MA|algorithmic_rent_setting"]["result"] == "pending"
    assert all(r["citation"] != ballot["citation"] for r in bo1.values())   # struck never exported
    # official formats: every address present; every result points at an exported, quoted rule
    rules_out = json.loads((out / "rules.json").read_text())["rules"]
    by_tid = {r["team_rule_id"]: r for r in rules_out}
    assert all(len(r["quoted_span"]) >= 20 and r["source_url"] for r in rules_out)
    assert all(r["category"] in config.CATEGORIES and r["level"] in ("state", "city") for r in rules_out)
    assert {r["jurisdiction"] for r in rules_out} >= {"CA", "San Francisco, CA", "Hoboken, NJ"}
    lk = json.loads((out / "lookups.json").read_text())
    assert lk["as_of"] == "2026-10-01" and set(lk["lookups"]) == {a["address_id"] for a in addrs}
    rows = [r for rs in lk["lookups"].values() for r in rs]
    assert rows and all(r["team_rule_id"] in by_tid and r["explanation"] for r in rows)
    assert set(rows[0]) == {"team_rule_id", "result", "explanation", "conflict_flag"}
    hb = lk["lookups"]["HB1"]
    assert any(r["conflict_flag"] for r in hb)
    fair_out = next(r for r in rules_out if "FAIR" in r["citation"])
    assert fair_out["status"] == "not_yet_effective" and fair_out["conflict_flag"]


def test_change_cases(workspace):
    rules, addrs, out = run_all(workspace)
    t = json.loads((out / "changes.json").read_text())
    assert set(t) == {"T1", "T2", "T3", "T4", "T5"}
    ca = {a["address_id"] for a in addrs if a["state"] == "CA"}
    assert set(t["T1"]["affected_address_ids"]) == ca
    assert t["T2"]["affected_address_ids"] == ["HB1"]              # only inside Hoboken (no JC fixture rule)
    assert t["T3"]["affected_address_ids"] == ["HB1", "JC1", "NW1"]
    assert t["T3"]["conflict_flag_address_ids"] == ["HB1"]         # conflict only where a local ban exists
    assert t["T4"]["affected_address_ids"] == ["BO1", "CB1"]
    assert t["T5"]["affected_address_ids"] == []


def test_hour16_ingest(workspace):
    run_all(workspace)
    cli.main(["--pack", str(workspace / "pack"), "ingest", str(config.ROOT / "fixtures" / "new_cambridge_ordinance.txt"),
              "--doc-id", "new_cambridge_ordinance", "--retrieval-date", "2026-10-04"])
    out = workspace / "out"
    t6 = json.loads((out / "changes.json").read_text())["T6"]
    assert t6["affected_address_ids"] == ["CB1"] and "2027-03-01" in t6["notes"]
    rules_out = {r["team_rule_id"]: r for r in json.loads((out / "rules.json").read_text())["rules"]}
    cb1 = json.loads((out / "lookups.json").read_text())["lookups"]["CB1"]
    fee = next(r for r in cb1 if rules_out[r["team_rule_id"]]["category"] == "application_screening_fees")
    assert fee["result"] == "not_yet_effective"


def test_site_payload(workspace):
    run_all(workspace)
    data = json.loads((workspace / "out" / "site" / "data.json").read_text())
    assert "2026-01-01" in data["dates"] and "2027-07-01" in data["dates"]
    assert len(data["results"]) == len(data["addresses"])
    assert (workspace / "out" / "site" / "index.html").exists()


def test_live_extraction_payload_matches_pipeline(workspace):
    from navigator.extract import prompts
    run_all(workspace)
    site = workspace / "out" / "site"
    live = json.loads((site / "live.json").read_text())
    assert live["system"] == prompts.EXTRACT_SYSTEM and live["schema"] == prompts.RULES_SCHEMA
    assert live["docs"] and all(d["text"].strip() for d in live["docs"])
    assert live["jurisdictions"]["MA"]["cambridge"] == "MA:city:cambridge"
    assert (site / "live.js").exists()
