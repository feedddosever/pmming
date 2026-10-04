"""Canonical jurisdictions and the per-address jurisdiction stack.

Ids: ``CA`` (state), ``CA:county:alameda``, ``CA:city:berkeley``. San Francisco is a consolidated
city-county: both ``CA:county:san-francisco`` and ``CA:city:san-francisco`` resolve to the single
city node, so rules are never stacked twice.
"""
from __future__ import annotations

import re

STATES = {
    "CA": "California",
    "NJ": "New Jersey",
    "MA": "Massachusetts",
}
STATE_BY_NAME = {v.lower(): k for k, v in STATES.items()}

# city slug -> (state, county slug, display name, census place/subdivision name)
CITIES = {
    ("CA", "los-angeles"): ("los-angeles", "Los Angeles", "Los Angeles city"),
    ("CA", "san-francisco"): ("san-francisco", "San Francisco", "San Francisco city"),
    ("CA", "san-diego"): ("san-diego", "San Diego", "San Diego city"),
    ("CA", "berkeley"): ("alameda", "Berkeley", "Berkeley city"),
    ("CA", "santa-ana"): ("orange", "Santa Ana", "Santa Ana city"),
    ("NJ", "jersey-city"): ("hudson", "Jersey City", "Jersey City city"),
    ("NJ", "hoboken"): ("hudson", "Hoboken", "Hoboken city"),
    ("NJ", "newark"): ("essex", "Newark", "Newark city"),
    ("MA", "boston"): ("suffolk", "Boston", "Boston city"),
    ("MA", "cambridge"): ("middlesex", "Cambridge", "Cambridge city"),
}
CONSOLIDATED = {("CA", "san-francisco")}

# Postal names that are neighborhoods of an in-scope city (offline fallback only).
POSTAL_ALIASES = {
    ("MA", s): "boston"
    for s in [
        "boston", "dorchester", "roxbury", "allston", "brighton", "jamaica plain", "charlestown",
        "south boston", "east boston", "roslindale", "west roxbury", "hyde park", "mattapan",
        "mission hill", "back bay", "dorchester center",
    ]
}
POSTAL_ALIASES.update({("MA", "cambridge"): "cambridge"})
for _st, _slug in CITIES:
    POSTAL_ALIASES.setdefault((_st, CITIES[(_st, _slug)][1].lower()), _slug)
# San Francisco and Los Angeles neighborhoods commonly used as postal names.
POSTAL_ALIASES.update({("CA", n): "los-angeles" for n in ["hollywood", "north hollywood", "van nuys", "encino",
                                                          "sherman oaks", "studio city", "san pedro", "wilmington",
                                                          "venice", "woodland hills", "reseda", "northridge",
                                                          "canoga park", "panorama city", "sylmar", "tarzana",
                                                          "winnetka", "sun valley", "playa vista", "harbor city"]})


def slug(name: str) -> str:
    s = (name or "").lower().strip()
    s = re.sub(r"\b(city|town|township|county|city and county) of\b", "", s)
    s = re.sub(r"\b(city|county)\b$", "", s.strip())
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def state_code(value: str | None) -> str | None:
    if not value:
        return None
    v = value.strip()
    if v.upper() in STATES:
        return v.upper()
    return STATE_BY_NAME.get(v.lower())


def canonical_id(level: str, state: str | None, name: str | None) -> str | None:
    st = state_code(state)
    if not st:
        return None
    level = (level or "").lower()
    if level == "state":
        return st
    low = (name or "").lower()
    for (cst, cslug), (_county, disp, _cn) in CITIES.items():  # known city names first ("Jersey City")
        if cst == st and re.search(rf"\b{re.escape(disp.lower())}\b", low):
            return f"{st}:city:{cslug}"
    s = slug(name or "")
    if not s:
        return None
    if level in ("county", "city_county", "city-county") and (st, s) in CONSOLIDATED:
        return f"{st}:city:{s}"
    if level in ("city", "municipal", "municipality", "city_county", "city-county", "local"):
        return f"{st}:city:{s}"
    if level == "county":
        return f"{st}:county:{s}"
    return f"{st}:city:{s}"


def stack_for(state: str, city_slug: str | None, county_slug: str | None = None) -> list[str]:
    """State > county > city. Unknown/out-of-scope city -> state (+ county if known)."""
    st = state_code(state) or state
    ids = [st]
    if city_slug and (st, city_slug) in CITIES:
        county = CITIES[(st, city_slug)][0]
        if (st, city_slug) not in CONSOLIDATED:
            ids.append(f"{st}:county:{county}")
        ids.append(f"{st}:city:{city_slug}")
    elif county_slug:
        ids.append(f"{st}:county:{county_slug}")
    return ids


def city_from_census_name(state: str, census_name: str | None) -> str | None:
    if not census_name:
        return None
    for (st, s), (_c, _disp, cname) in CITIES.items():
        if st == state and cname.lower() == census_name.lower():
            return s
    return None


def label(jid: str) -> str:
    parts = jid.split(":")
    if len(parts) == 1:
        return STATES.get(jid, jid)
    st, level, s = parts
    if level == "city" and (st, s) in CITIES:
        disp = CITIES[(st, s)][1]
        return f"City and County of {disp}" if (st, s) in CONSOLIDATED else f"City of {disp}"
    return f"{s.replace('-', ' ').title()} County" if level == "county" else s.replace("-", " ").title()
