"""Derive building facts the CSV leaves blank from the assessor use code/description.

Rules live in config/use_codes.json (data, not code). Known values in the CSV always win;
derived values only fill gaps, and unit counts become a range (units_min/units_max) that the
predicate engine evaluates with three-valued logic.
"""
from __future__ import annotations

import json
import re

from .. import config


def _rules():
    p = config.CONFIG_DIR / "use_codes.json"
    return json.loads(p.read_text()) if p.exists() else {"rules": [], "default": {}}


def enrich(facts: dict) -> dict:
    f = dict(facts)
    cfg = _rules()
    desc = str(f.get("use_description") or "")
    code = str(f.get("use_code") or "")
    derived = {}
    for r in cfg["rules"]:
        m = None
        if "match" in r:
            m = re.search(r["match"], desc)
        elif "match_code" in r:
            m = re.search(r["match_code"], code)
        if not m:
            continue
        if r.get("units_sum_all"):
            nums = [int(x) for x in re.findall(r"(?i)(?<![\d.])(\d+)U(?![a-z])", desc)]
            if nums:
                derived["units_min"] = max(derived.get("units_min", 0), max(nums))
                derived["units_max"] = min(derived.get("units_max", 10**6), sum(nums))
        for k in ("units_min", "units_max"):
            if k in r:
                v = r[k]
                derived[k] = max(derived.get(k, 0), v) if k == "units_min" else min(derived.get(k, 10**6), v)
            g = r.get(f"{k}_group")
            if g:
                v = int(m.group(g))
                derived[k] = max(derived.get(k, 0), v) if k == "units_min" else min(derived.get(k, 10**6), v)
        for k in ("building_type", "subsidized"):
            if k in r and k not in derived:
                derived[k] = r[k]
    for k, v in (cfg.get("default") or {}).items():
        if not k.startswith("_"):
            derived.setdefault(k, v)
    for k, v in derived.items():
        if f.get(k) in (None, ""):
            f[k] = v
    f["derived_facts"] = sorted(k for k in derived if facts.get(k) in (None, ""))
    return f
