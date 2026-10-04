"""Check an agent's answer before the pipeline sees it.

    python -m navigator.agent_check <request.json>

Validates cache/agent_responses/<key>.json against the request's schema and reports every quote
that is not found verbatim in the request's document (those rules would be dropped later)."""
from __future__ import annotations

import json
import re
import sys

import jsonschema

from .extract.verify import locate


def main(path: str) -> int:
    req = json.loads(open(path).read())
    try:
        data = json.loads(open(req["response_path"]).read())
    except FileNotFoundError:
        print("NO RESPONSE FILE:", req["response_path"])
        return 1
    except json.JSONDecodeError as e:
        print("INVALID JSON:", e)
        return 1
    try:
        jsonschema.validate(data, req["schema"])
    except jsonschema.ValidationError as e:
        print("SCHEMA ERROR:", e.message, "at", "/".join(map(str, e.path)))
        return 1
    m = re.search(r"<document>\n(.*)\n</document>", req["user"], re.S)
    text = m.group(1) if m else req["user"]
    quotes = [r["quote"] for r in data.get("rules", [])] if "rules" in data else ([data["quote"]] if data.get("quote") else [])
    bad = [q for q in quotes if not locate(q, text)]
    for q in bad:
        print("QUOTE NOT VERBATIM:", q[:160])
    n = len(data.get("rules", [])) if "rules" in data else int(bool(data.get("exists")))
    print(f"OK schema; {n} record(s); {len(bad)} quote(s) not verbatim")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
