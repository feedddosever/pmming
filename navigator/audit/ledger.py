"""Append-only JSONL audit ledger: every source hash, model call, and output decision."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone

from .. import config

_lock = threading.Lock()
_enabled = True


def path():
    return config.OUT_DIR / "audit_log.jsonl"


def enable(flag: bool):
    global _enabled
    _enabled = flag


def log(event: str, **fields):
    if not _enabled:
        return
    rec = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "event": event, **fields}
    config.OUT_DIR.mkdir(parents=True, exist_ok=True)
    with _lock, path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
