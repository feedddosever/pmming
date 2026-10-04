"""Fetch the few public sources the starter pack lists as link-only but the change tests need.

Each page is fetched once (no crawling), converted to text with a SOURCE/RETRIEVED header like
the starter-pack corpus, and listed in data/supplement/manifest.csv. Pages whose publishers
block automated access (ecode360, marked "check-terms" in the pack) are not fetched.
Output is git-ignored; rerun this script to reproduce it.
"""
from __future__ import annotations

import csv
import hashlib
import html
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "supplement"
SOURCES = [
    ("S001", "Hoboken, NJ", "official",
     "https://hobokennj.iqm2.com/Citizens/Detail_LegiFile.aspx?ID=12291&MeetingID=2943"),
    ("S002", "Jersey City, NJ", "official", "https://cityofjerseycity.civicweb.net/document/433505/"),
    ("S003", "MA", "secondary (law firm / news / mirror)",
     "https://www.wbur.org/news/2026/06/23/massachusetts-high-court-rent-control-ballot-question-struck"),
]


def to_text(resp: httpx.Response) -> str:
    if "pdf" in resp.headers.get("content-type", ""):
        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            f.write(resp.content)
            f.flush()
            return subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True, text=True).stdout
    t = re.sub(r"(?s)<script.*?</script>|<style.*?</style>|<nav.*?</nav>|<footer.*?</footer>", "", resp.text)
    t = html.unescape(re.sub(r"<[^>]+>", "\n", t))
    t = "\n".join(line.strip() for line in t.splitlines())
    return re.sub(r"\n{2,}", "\n", t).strip()


def main():
    (OUT / "text").mkdir(parents=True, exist_ok=True)
    rows = []
    with httpx.Client(follow_redirects=True, timeout=60, headers={"User-Agent": "Mozilla/5.0 (rental-law-navigator)"}) as c:
        for doc_id, juris, stype, url in SOURCES:
            r = c.get(url)
            r.raise_for_status()
            now = datetime.now(timezone.utc)
            text = f"SOURCE: {url}\nRETRIEVED: {now:%Y-%m-%d %H:%M} UTC\n\n{to_text(r)}\n"
            p = OUT / "text" / f"{doc_id}.txt"
            p.write_text(text)
            rows.append({"doc_id": doc_id, "jurisdictions": juris, "url": url, "source_type": stype,
                         "capture": "supplement", "retrieved_at": f"{now:%Y-%m-%dT%H:%MZ}",
                         "sha256": hashlib.sha256(text.encode()).hexdigest(), "text_file": f"text/{doc_id}.txt",
                         "status": "ok"})
            print(doc_id, len(text), "chars", url)
    with (OUT / "manifest.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
