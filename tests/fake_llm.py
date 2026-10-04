"""Fake LLM for tests: returns what a correct extractor would return for the synthetic fixtures.
Quotes are copied from the fixture texts so the citation lock is exercised for real."""
import json
import re


def C(fact, op, num=None, text=None, lst=None):
    return {"fact": fact, "op": op, "value_number": num, "value_text": text, "value_list": lst or []}


def R(**kw):
    base = {"key_value": None, "coverage_text": "", "applies_if": [], "exemptions": [], "effective_date": None,
            "end_date": None, "status": "enacted", "yields_to": [], "may_preempt": [], "penalty": None,
            "requirement_es": "Resumen en español.", "confidence": 0.9, "title": "fixture"}
    base.update(kw)
    return base


CANNED = {
    "fx_ca_rent": [R(category="rent_increase_limits", jurisdiction_level="state", jurisdiction_state="CA",
                     jurisdiction_name="California", citation="Cal. Fixture Code Section 100",
                     requirement="Rent can go up at most 5% plus inflation, never more than 10% a year.",
                     key_value="5% + CPI, max 10%",
                     exemptions=[{"label": "built within 15 years", "all": [C("age_years", "lte", 15)]}],
                     yields_to=[{"category": "rent_increase_limits", "level": "city", "note": None}],
                     effective_date="2020-01-01",
                     quote="An owner of residential real property shall not, over the course of any 12-month period, increase the gross rental rate for a dwelling or a unit more than 5 percent plus the percentage change in the cost of living, or 10 percent, whichever is lower.")],
    "fx_sf_rent": [R(category="rent_increase_limits", jurisdiction_level="county", jurisdiction_state="California",
                     jurisdiction_name="City and County of San Francisco", citation="S.F. Fixture Admin. Code ch. 37",
                     requirement="Older buildings: yearly increase limited to 60% of inflation.",
                     applies_if=[C("year_built", "before_date", text="1979-06-13")],
                     quote="Rental units for which a certificate of occupancy was first issued on or before June 13, 1979 are subject to this Chapter.")],
    "fx_ca_algo": [R(category="algorithmic_rent_setting", jurisdiction_level="state", jurisdiction_state="CA",
                     jurisdiction_name="California", citation="AB 325 (2025)", title="AB 325",
                     requirement="Using a shared pricing algorithm to set rents is illegal.",
                     effective_date="2026-01-01",
                     quote="It shall be unlawful for a person to use or distribute a common pricing algorithm as part of a contract, combination in the form of a trust, or conspiracy to restrain trade or commerce.")],
    "fx_nj_fair": [R(category="algorithmic_rent_setting", jurisdiction_level="state", jurisdiction_state="NJ",
                     jurisdiction_name="New Jersey", citation="P.L.2026, c.43 (FAIR Act)", title="FAIR Act",
                     requirement="Landlords may not use rent algorithms fed with competitors' private data.",
                     effective_date="2027-07-01",
                     may_preempt=[{"category": "algorithmic_rent_setting", "level": "city", "note": "supersedes municipal ordinances"}],
                     # whitespace and quote style differ from the source on purpose
                     quote="No landlord  shall use an algorithmic device that relies on nonpublic competitor data to set or recommend rent for a dwelling unit.")],
    "fx_hoboken_algo": [R(category="algorithmic_rent_setting", jurisdiction_level="city", jurisdiction_state="NJ",
                          jurisdiction_name="Hoboken", citation="Hoboken Fixture Code ch. 158, Art. II",
                          requirement="Hoboken bans rent-setting algorithms.", effective_date="2025-07-01",
                          quote="No landlord shall use, license or rely upon any algorithmic device to set rents for residential rental units within the City of Hoboken.")],
    "fx_ma_rent": [],
    "fx_ma_pending": [R(category="algorithmic_rent_setting", jurisdiction_level="state", jurisdiction_state="MA",
                        jurisdiction_name="Massachusetts", citation="S.2983", title="S.2983", status="pending",
                        requirement="Proposed: would ban rent algorithms using competitors' private data.",
                        quote="A landlord shall not use a rent-setting algorithm that incorporates nonpublic competitor data to determine rent for a residential dwelling unit.")],
    "fx_ma_ballot": [R(category="rent_increase_limits", jurisdiction_level="state", jurisdiction_state="MA",
                       jurisdiction_name="Massachusetts", citation="2026 Ballot Question (rent control)", status="struck",
                       requirement="A proposed statewide rent-control question was removed from the ballot.",
                       quote="this quote is invented and must fail the citation lock because it is not in the text")],
    "new_cambridge_ordinance": [R(category="application_screening_fees", jurisdiction_level="city", jurisdiction_state="MA",
                                  jurisdiction_name="Cambridge", citation="Cambridge Fixture Ord. 2026-99",
                                  requirement="No application fees in buildings with 3+ units.",
                                  applies_if=[C("units", "gte", 3)], effective_date="2027-03-01",
                                  quote="No owner of a residential building containing three or more units shall charge an application fee to a prospective tenant.")],
}


def fake(system, user, schema_name):
    if schema_name == "rules":
        doc_id = re.search(r"Document id: (\S+)", user).group(1)
        return {"rules": json.loads(json.dumps(CANNED.get(doc_id, [])))}
    if schema_name == "no_rule":
        if "rent_increase_limits" in user and ("Boston" in user or "Cambridge" in user) and "fx_ma_rent" in user:
            return {"exists": True, "explanation": "State law prohibits local rent control.",
                    "citation": "M.G.L. Fixture c.40P",
                    "quote": "No city or town shall enact, maintain or enforce any ordinance or by-law regulating the amount of rent charged for the use or occupancy of residential property."}
        return {"exists": False, "explanation": "No explicit evidence.", "citation": None, "quote": None}
    if schema_name == "normalize":
        return {"clauses": []}
    if schema_name == "review":
        rec = json.loads(user.split("Record:\n", 1)[1].split("\n\nDocument id:", 1)[0])
        return {"decision": "keep", "reason": "fixture", "rule": rec}
    raise AssertionError(schema_name)
