"""Load the official starter pack without knowing its exact formats in advance.

Files are found by content, not by name: the manifest is the CSV whose header has a doc-id and a
URL/path column; the address file is the CSV with street/zip/year-built-like columns; JSON files
are classified as schema (has "$schema" or "properties"), dev key, or change cases. Column names
are matched against alias lists, and ``config/column_map.json`` can override anything at kickoff.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from .. import config

ALIASES = {
    "doc_id": ["doc_id", "document_id", "id", "source_id", "doc"],
    "path": ["path", "file", "filename", "text_file", "local_path", "txt_path", "file_path"],
    "url": ["url", "source_url", "link"],
    "title": ["title", "name", "document_title"],
    "retrieval_date": ["retrieval_date", "retrieved", "retrieved_on", "accessed", "date_retrieved", "retrieved_at"],
    "jurisdiction": ["jurisdiction", "jurisdiction_name", "place"],
    "doc_type": ["type", "doc_type", "document_type", "kind", "source_type"],
    # addresses
    "address_id": ["address_id", "id", "property_id", "parcel_id", "apn", "record_id"],
    "street": ["street", "address", "street_address", "site_address", "address_line"],
    "city": ["city", "postal_city", "municipality", "town"],
    "state": ["state", "st", "state_code"],
    "zip": ["zip", "zipcode", "zip_code", "postal_code", "postcode"],
    "year_built": ["year_built", "yearbuilt", "yr_built", "built_year", "year"],
    "units": ["units", "unit_count", "num_units", "number_of_units", "total_units", "dwelling_units"],
    "use_code": ["use_code", "usecode", "land_use", "property_use", "use", "class_code", "property_class"],
}


def _load_overrides() -> dict:
    p = config.CONFIG_DIR / "column_map.json"
    return json.loads(p.read_text()) if p.exists() else {}


def _pick(header: list[str], key: str, overrides: dict) -> str | None:
    if key in overrides:
        return overrides[key]
    low = {h.lower().strip(): h for h in header}
    for a in ALIASES[key]:
        if a in low:
            return low[a]
    return None


def _read_csv(p: Path) -> tuple[list[str], list[dict]]:
    with p.open(newline="", encoding="utf-8-sig") as f:
        r = csv.DictReader(f)
        return list(r.fieldnames or []), list(r)


def sha256_text(t: str) -> str:
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


class StarterPack:
    def __init__(self, root: Path | None = None):
        self.root = Path(root or config.STARTER_PACK)
        self.overrides = _load_overrides()
        self.manifest_path = self.addresses_path = self.schema_path = None
        self.dev_key_path = self.changes_path = self.score_script = None
        self._classify()

    # ---------- discovery ----------
    def _classify(self):
        for p in sorted(self.root.rglob("*")):
            if not p.is_file():
                continue
            name = p.name.lower()
            if name.endswith(".py") and "score" in name:
                self.score_script = p
            elif name.endswith(".csv"):
                header, _ = _read_csv(p)
                h = {x.lower() for x in header}
                if h & {"year_built", "yearbuilt", "units", "unit_count", "zip", "zipcode", "zip_code"}:
                    self.addresses_path = self.addresses_path or p
                elif h & {"url", "source_url", "path", "file", "filename"}:
                    self.manifest_path = self.manifest_path or p
            elif name.endswith(".json"):
                try:
                    data = json.loads(p.read_text())
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                if isinstance(data, dict) and ("$schema" in data or ("properties" in data and "type" in data)):
                    self.schema_path = self.schema_path or p
                elif any(k in name for k in ("change", "test_case", "tests")):
                    self.changes_path = self.changes_path or p
                elif any(k in name for k in ("key", "answer", "expected", "dev")):
                    self.dev_key_path = self.dev_key_path or p

    def describe(self) -> dict:
        return {k: str(getattr(self, k)) if getattr(self, k) else None for k in
                ("manifest_path", "addresses_path", "schema_path", "dev_key_path", "changes_path", "score_script")}

    # ---------- corpus ----------
    def documents(self) -> list[dict]:
        docs = []
        if self.manifest_path:
            header, rows = _read_csv(self.manifest_path)
            col = {k: _pick(header, k, self.overrides.get("manifest", {})) for k in
                   ("doc_id", "path", "url", "title", "retrieval_date", "jurisdiction", "doc_type")}
            for i, row in enumerate(rows):
                doc_id = (row.get(col["doc_id"]) if col["doc_id"] else None) or f"doc{i:03d}"
                text = ""
                if col["path"] and row.get(col["path"]):
                    text = self._read_text(row[col["path"]], doc_id)
                else:
                    text = self._read_text(None, doc_id)
                docs.append(self._doc(doc_id, text, row, col))
        else:  # no manifest: every .txt is a document
            for p in sorted(self.root.rglob("*.txt")):
                docs.append(self._doc(p.stem, p.read_text(encoding="utf-8", errors="replace"), {}, {}))
        return docs

    def _read_text(self, rel: str | None, doc_id: str) -> str:
        cands = []
        if rel:
            cands += [self.root / rel, self.manifest_path.parent / rel]
        cands += list(self.root.rglob(f"{doc_id}.txt")) + list(self.root.rglob(f"{doc_id}.md"))
        for c in cands:
            if c.exists() and c.is_file():
                return c.read_text(encoding="utf-8", errors="replace")
        return ""

    @staticmethod
    def _doc(doc_id, text, row, col):
        g = lambda k: (row.get(col[k]) if col.get(k) else None)  # noqa: E731
        return {
            "doc_id": str(doc_id),
            "title": g("title") or str(doc_id),
            "url": g("url"),
            "retrieval_date": g("retrieval_date"),
            "jurisdiction_hint": g("jurisdiction"),
            "doc_type": g("doc_type"),
            "text": text,
            "link_only": len(text.strip()) < 200,
            "sha256": sha256_text(text),
        }

    # ---------- addresses ----------
    def addresses(self) -> list[dict]:
        if not self.addresses_path:
            return []
        header, rows = _read_csv(self.addresses_path)
        col = {k: _pick(header, k, self.overrides.get("addresses", {})) for k in
               ("address_id", "street", "city", "state", "zip", "year_built", "units", "use_code")}
        out = []
        for i, row in enumerate(rows):
            g = lambda k: (row.get(col[k]).strip() if col.get(k) and row.get(col[k]) is not None else None)  # noqa: E731
            yb, units = _int(g("year_built")), _int(g("units"))
            facts = {"year_built": yb if yb and 1700 <= yb <= 2100 else None,  # 0 / blanks mean "missing"
                     "units": units if units and units > 0 else None, "use_code": g("use_code") or None}
            # Keep every other column as a fact too (owner type etc. if the pack has them).
            for h in header:
                if h not in col.values() and row.get(h) not in (None, ""):
                    facts.setdefault(h.lower(), row[h])
            out.append({
                "address_id": g("address_id") or f"A{i:04d}",
                "street": g("street"), "city": g("city"), "state": (g("state") or "").upper() or None,
                "zip": (g("zip") or "")[:5] or None, "facts": facts,
            })
        return out

    def schema(self) -> dict | None:
        return json.loads(self.schema_path.read_text()) if self.schema_path else None

    def dev_key(self):
        return json.loads(self.dev_key_path.read_text()) if self.dev_key_path else None

    def change_cases(self):
        return json.loads(self.changes_path.read_text()) if self.changes_path else None


def _int(v):
    if v in (None, ""):
        return None
    try:
        return int(float(str(v).replace(",", "")))
    except ValueError:
        return None
