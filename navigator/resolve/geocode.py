"""Resolve addresses to a jurisdiction stack.

Primary: Census Geocoder ``geographies/onelineaddress`` (free, no key), which returns the
incorporated place (CA) and county subdivision (NJ/MA townships are the municipalities there).
We never trust the postal city name: "Los Angeles" mail addresses include unincorporated county
areas. Every response is cached on disk so reruns are offline and deterministic.

Fallback (no network): postal city/neighborhood alias table, marked ``confidence: low``.
"""
from __future__ import annotations

import hashlib
import re
import json
from concurrent.futures import ThreadPoolExecutor

import httpx

from .. import config
from .jurisdictions import CITIES, POSTAL_ALIASES, city_from_census_name, slug, stack_for

CENSUS_URL = "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress"
CACHE = config.CACHE_DIR / "geocode"


def _key(line: str) -> str:
    return hashlib.sha1(line.lower().encode()).hexdigest()


def census_lookup(line: str, client: httpx.Client | None = None) -> dict | None:
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / f"{_key(line)}.json"
    if p.exists():
        return json.loads(p.read_text())
    params = {"address": line, "benchmark": "Public_AR_Current", "vintage": "Current_Current",
              "layers": "all", "format": "json"}
    try:
        c = client or httpx.Client(timeout=30)
        r = c.get(CENSUS_URL, params=params)
        r.raise_for_status()
        data = r.json()
    except (httpx.HTTPError, ValueError):
        return None
    p.write_text(json.dumps(data))
    return data


def _parse_census(data: dict | None, prefer: str | None = None):
    try:
        m = data["result"]["addressMatches"]
    except (TypeError, KeyError):
        return None
    if not m:
        return {"match": False}
    best = m[0]
    if prefer and len(m) > 1:  # tie: prefer the candidate inside the postal city
        for cand in m:
            g = cand.get("geographies", {})
            names = [(g.get(k) or [{}])[0].get("NAME", "") for k in ("Incorporated Places", "County Subdivisions")]
            if any(n.lower().startswith(prefer.lower()) for n in names):
                best = cand
                break
    m = [best] + [x for x in m if x is not best]
    geo = m[0].get("geographies", {})
    first = lambda k: (geo.get(k) or [{}])[0]  # noqa: E731
    state = first("States").get("STUSAB")
    county = first("Counties").get("NAME")
    place = first("Incorporated Places").get("NAME")
    cousub = first("County Subdivisions").get("NAME")
    return {"match": True, "state": state, "county": county, "place": place, "cousub": cousub,
            "matched_address": m[0].get("matchedAddress"), "coordinates": m[0].get("coordinates"),
            "ties": len(m) > 1}


def _normalize_street(street: str | None) -> str | None:
    if not street:
        return street
    s = re.sub(r"\b0+(\d+(ST|ND|RD|TH))\b", r"\1", street.upper())   # 05TH -> 5TH
    s = re.sub(r"\bAV\b", "AVE", s)
    return s


def resolve_one(addr: dict, use_network: bool = True, client=None) -> dict:
    parsed = None
    if use_network:
        line = ", ".join(x for x in [addr.get("street"), addr.get("city"), addr.get("state"), addr.get("zip")] if x)
        parsed = _parse_census(census_lookup(line, client), addr.get("city"))
        if not (parsed and parsed.get("match")):
            # retry: normalized street, and without a possibly wrong ZIP
            line2 = ", ".join(x for x in [_normalize_street(addr.get("street")), addr.get("city"), addr.get("state")] if x)
            retry = _parse_census(census_lookup(line2, client), addr.get("city"))
            if retry and retry.get("match"):
                parsed = retry
    st = addr.get("state")
    if parsed and parsed.get("match"):
        st = parsed["state"] or st
        city = city_from_census_name(st, parsed.get("place")) or city_from_census_name(st, parsed.get("cousub"))
        county = slug(parsed.get("county") or "")
        conf = "medium" if parsed.get("ties") else "high"
        method = "census"
        note = None if city else f"outside in-scope cities (place: {parsed.get('place') or 'unincorporated'})"
    else:
        city = POSTAL_ALIASES.get((st, (addr.get("city") or "").strip().lower()))
        county = CITIES[(st, city)][0] if city else None
        conf, method = "low", "postal_alias"
        note = "offline fallback from postal city; verify incorporated-place boundary"
        if parsed and not parsed.get("match"):
            note = "census: no match; " + note
    return {**addr, "stack": stack_for(st, city, county), "city_slug": city,
            "geocode": {"method": method, "confidence": conf, "note": note,
                        "matched": parsed.get("matched_address") if parsed else None}}


def resolve_all(addresses: list[dict], use_network: bool = True, workers: int = 8) -> list[dict]:
    if not use_network:
        return [resolve_one(a, False) for a in addresses]
    with httpx.Client(timeout=30) as client, ThreadPoolExecutor(workers) as ex:
        return list(ex.map(lambda a: resolve_one(a, True, client), addresses))
