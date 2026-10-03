from datetime import date

from navigator.apply import predicates as P
from navigator.apply.status import status_on
from navigator.extract.verify import lock_quote
from navigator.resolve.jurisdictions import canonical_id, stack_for
from navigator.resolve.geocode import resolve_one

D = date(2026, 10, 1)


def C(fact, op, num=None, text=None, lst=None):
    return {"fact": fact, "op": op, "value_number": num, "value_text": text, "value_list": lst or []}


def test_kleene():
    assert P.k_and([True, None]) is None and P.k_and([False, None]) is False
    assert P.k_or([True, None]) is True and P.k_or([False, None]) is None


def test_missing_fact_is_unknown_not_false():
    v, reasons = P.evaluate({"applies_if": [C("units", "gte", 3)]}, {"units": None}, D)
    assert v is None and reasons


def test_known_fact_resolves_exemption_with_unknown_owner():
    cov = {"applies_if": [], "exemptions": [{"label": "single-family owned by natural person",
                                             "all": [C("units", "lte", 1), C("owner_type", "eq", text="natural_person")]}]}
    assert P.evaluate(cov, {"units": 20}, D)[0] is True      # exemption false although owner unknown
    assert P.evaluate(cov, {"units": 1}, D)[0] is None       # depends on owner -> unknown


def test_age_is_relative_to_as_of_and_boundary_is_unknown():
    cov = {"exemptions": [{"label": "new", "all": [C("age_years", "lte", 15)]}]}
    assert P.evaluate(cov, {"year_built": 2018}, D)[0] is False   # exempt
    assert P.evaluate(cov, {"year_built": 1990}, D)[0] is True
    assert P.evaluate(cov, {"year_built": 2011}, D)[0] is False   # 14 or 15: exempt either way
    assert P.evaluate(cov, {"year_built": 2010}, D)[0] is None    # 15 or 16: cannot tell


def test_certificate_of_occupancy_proxy():
    c = {"applies_if": [C("year_built", "before_date", text="1979-06-13")]}
    assert P.evaluate(c, {"year_built": 1962}, D)[0] is True
    assert P.evaluate(c, {"year_built": 1979}, D)[0] is None
    assert P.evaluate(c, {"year_built": 1985}, D)[0] is False


def test_status_semantics():
    assert status_on({"status": "pending"}, D) == "pending"
    assert status_on({"status": "struck"}, D) == "struck"
    assert status_on({"status": "enacted", "effective_date": "2027-07-01"}, D) == "not_yet_effective"
    assert status_on({"status": "enacted", "effective_date": "2027-07-01"}, date(2027, 7, 1)) == "in_force"
    assert status_on({"status": "enacted", "effective_date": "2020-01-01", "end_date": "2024-07-01"}, D) == "expired"


def test_quote_lock_is_verbatim_only():
    text = "Intro.  The  landlord “shall not” raise rent above 5 percent in any year. Outro."
    ok = lock_quote('The landlord "shall not" raise rent above 5 percent in any year.', text)
    assert ok["verified"] and ok["quote"] in text
    bad = lock_quote("The landlord may raise rent above 5 percent in any year whenever it wants to.", text)
    assert not bad["verified"] and bad["quote"] is None


def test_jurisdiction_ids_and_sf_consolidation():
    assert canonical_id("county", "California", "City and County of San Francisco") == "CA:city:san-francisco"
    assert canonical_id("state", "NJ", None) == "NJ"
    assert stack_for("CA", "san-francisco") == ["CA", "CA:city:san-francisco"]
    assert stack_for("CA", "berkeley") == ["CA", "CA:county:alameda", "CA:city:berkeley"]


def test_offline_postal_alias_is_low_confidence():
    a = resolve_one({"address_id": "x", "street": "1 A St", "city": "Dorchester", "state": "MA", "zip": "02124", "facts": {}}, use_network=False)
    assert a["stack"][-1] == "MA:city:boston" and a["geocode"]["confidence"] == "low"
