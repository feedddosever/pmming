"""Citation lock: quotes must appear verbatim in the source document.

Allowed normalization is limited to whitespace runs and typographic quotes/dashes, and the returned
span is always the *original* substring of the document, so the exported quote is found in the
corpus character for character. No fuzzy matching.
"""
from __future__ import annotations

import re

_TRANS = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-",
                        " ": " ", "§": "§"})


def _normalize_with_map(s: str):
    out, idx = [], []
    prev_space = False
    for i, ch in enumerate(s.translate(_TRANS)):
        if ch.isspace():
            if prev_space:
                continue
            out.append(" ")
            idx.append(i)
            prev_space = True
        else:
            out.append(ch)
            idx.append(i)
            prev_space = False
    return "".join(out), idx


def locate(quote: str | None, text: str) -> tuple[int, int] | None:
    if not quote or not text:
        return None
    q = " ".join(quote.translate(_TRANS).split())
    if len(q) < 20:
        return None
    norm, idx = _normalize_with_map(text)
    pos = norm.find(q)
    if pos < 0:
        return None
    start = idx[pos]
    end = idx[pos + len(q) - 1] + 1
    return start, end


def lock_quote(quote: str | None, text: str) -> dict:
    """Return {"quote", "start", "end", "verified", "method"}."""
    span = locate(quote, text)
    if span:
        return {"quote": text[span[0]:span[1]], "start": span[0], "end": span[1], "verified": True, "method": "verbatim"}
    # Fall back to the longest sentence of the quote that is itself verbatim (still exact).
    best = None
    for frag in sorted(re.split(r"(?<=[.;:])\s+", quote or ""), key=len, reverse=True):
        if len(frag) < 60:
            break
        span = locate(frag, text)
        if span:
            best = span
            break
    if best:
        return {"quote": text[best[0]:best[1]], "start": best[0], "end": best[1], "verified": True,
                "method": "verbatim_fragment"}
    return {"quote": None, "start": None, "end": None, "verified": False, "method": "unverified"}
