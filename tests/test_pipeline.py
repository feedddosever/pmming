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
    assert nr == {"MA:city:boston|rent_increase|no_rule", "MA:city:cambridge|rent_increase|no_rule"}

    sf1 = results(addrs, rules, "SF1")        # 1962: local ordinance applies, state cap yields
    assert sf1["CA:city:san-francisco|rent_increase"]["result"] == "applies"
    assert sf1["CA|rent_increase"]["result"] == "superseded"
    sf2 = results(addrs, rules, "SF2")        # built 1979: local coverage unknown -> state unknown
    assert sf2["CA:city:san-francisco|rent_increase"]["result"] == "unknown"
    assert sf2["CA|rent_increase"]["result"] == "unknown"
    sf3 = results(addrs, rules, "SF3")        # 2018: state 15-year exemption, local not covered
    assert "CA|rent_increase" not in sf3 and "CA:city:san-francisco|rent_increase" not in sf3
    sd1 = results(addrs, rules, "SD1")        # no year built -> unknown, never "does not apply"
    assert sd1["CA|rent_increase"]["result"] == "unknown"
    hb1 = results(addrs, rules, "HB1")
    assert hb1["NJ|algorithmic_rent_setting"]["result"] == "not_yet_effective"
    assert hb1["NJ:city:hoboken|algorithmic_rent_setting"]["flags"][0]["type"] == "conflict"
    bo1 = results(addrs, rules, "BO1")
    assert bo1["MA|algorithmic_rent_setting"]["result"] == "pending"
    assert all(r["citation"] != ballot["citation"] for r in bo1.values())   # struck never exported
    # every "applies" carries a verified quote and retrieval date
    lk = json.loads((out / "lookups.json").read_text())
    applies = [r for a in lk["addresses"] for r in a["results"] if r["result"] == "applies"]
    assert applies and all(r["quote"] and r["retrieval_date"] for r in applies)


def test_change_cases(workspace):
    rules, addrs, out = run_all(workspace)
    t = {x["id"]: x for x in json.loads((out / "changes.json").read_text())["tests"]}
    ca = {a["address_id"] for a in addrs if a["state"] == "CA"}
    assert set(t["T1"]["affected_addresses"]) == ca
    assert set(t["T2"]["affected_addresses"]) == {"HB1"}           # only inside Hoboken (no JC fixture rule)
    assert set(t["T3"]["affected_addresses"]) == {"HB1", "JC1", "NW1"}
    assert t["T3"]["conflicts"] == ["HB1"]                         # conflict only where a local ban exists
    assert set(t["T4"]["affected_addresses"]) == {"BO1", "CB1"}
    assert t["T5"]["affected_addresses"] == []


def test_hour16_ingest(workspace):
    run_all(workspace)
    cli.main(["--pack", str(workspace / "pack"), "ingest", str(config.ROOT / "fixtures" / "new_cambridge_ordinance.txt"),
              "--doc-id", "new_cambridge_ordinance", "--retrieval-date", "2026-10-04"])
    out = workspace / "out"
    t6 = next(x for x in json.loads((out / "changes.json").read_text())["tests"] if x["id"] == "T6")
    assert t6["affected_addresses"] == ["CB1"] and t6["after"] == "2027-03-01"
    cb1 = next(a for a in json.loads((out / "lookups.json").read_text())["addresses"] if a["address_id"] == "CB1")
    fee = next(r for r in cb1["results"] if r["category"] == "application_screening_fee")
    assert fee["result"] == "not_yet_effective"


def test_site_payload(workspace):
    run_all(workspace)
    data = json.loads((workspace / "out" / "site" / "data.json").read_text())
    assert "2026-01-01" in data["dates"] and "2027-07-01" in data["dates"]
    assert len(data["results"]) == len(data["addresses"])
    assert (workspace / "out" / "site" / "index.html").exists()
