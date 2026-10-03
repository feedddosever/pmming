"""Paths and settings. Everything is overridable through environment variables."""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

STARTER_PACK = Path(os.environ.get("NAV_STARTER_PACK", ROOT / "data" / "starter_pack"))
OUT_DIR = Path(os.environ.get("NAV_OUT", ROOT / "out"))
CACHE_DIR = Path(os.environ.get("NAV_CACHE", ROOT / "cache"))
CONFIG_DIR = Path(os.environ.get("NAV_CONFIG", ROOT / "config"))

# The brief's answers are "as of Oct 1, 2026". Never use the system clock by default.
DEFAULT_AS_OF = date.fromisoformat(os.environ.get("NAV_AS_OF", "2026-10-01"))

# LLM: "anthropic" (live + cache), "replay" (cache only), "fake" (tests).
LLM_MODE = os.environ.get("NAV_LLM", "anthropic")
LLM_MODEL = os.environ.get("NAV_MODEL", "claude-opus-5-5")
LLM_EFFORT = os.environ.get("NAV_EFFORT", "high")
PROMPT_VERSION = "2026-10-03.1"

CATEGORIES = [
    "rent_increase",
    "just_cause_eviction",
    "security_deposit",
    "application_screening_fee",
    "screening_restriction",
    "algorithmic_rent_setting",
]

CATEGORY_LABELS = {
    "rent_increase": ("Rent increase limits", "Límites de aumento de renta"),
    "just_cause_eviction": ("Just-cause eviction", "Desalojo con causa justificada"),
    "security_deposit": ("Security deposits", "Depósitos de garantía"),
    "application_screening_fee": ("Application & screening fees", "Cuotas de solicitud y evaluación"),
    "screening_restriction": ("Screening restrictions", "Restricciones de evaluación"),
    "algorithmic_rent_setting": ("Algorithmic rent-setting", "Fijación algorítmica de rentas"),
}

# Lookup result values, as named in the brief.
RESULTS = ["applies", "unknown", "superseded", "not_yet_effective", "pending"]
