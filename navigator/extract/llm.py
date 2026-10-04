"""LLM access with a deterministic replay cache.

Modes (``NAV_LLM``):
* ``anthropic`` - call the API, cache every response under ``cache/llm/`` (default)
* ``replay``    - cache only; a miss is an error (offline demo reruns, reproducibility)
* ``fake``      - a Python callable installed by tests via ``set_fake``

Responses use structured outputs (``output_config.format``), so the returned text is valid JSON.
Server-side refusal fallbacks are enabled: if a request is declined on the primary model the API
retries on a fallback model instead of failing the extraction run.
"""
from __future__ import annotations

import hashlib
import json
from typing import Callable

from .. import config

_fake: Callable[[str, str, str], dict] | None = None


class LLMError(RuntimeError):
    pass


class LLMPending(LLMError):
    """Agent mode: the request was queued for a Claude Code agent and has no answer yet."""


AGENT_MODEL = "claude-code-agent"


def agent_dirs():
    req, resp = config.CACHE_DIR / "agent_requests", config.CACHE_DIR / "agent_responses"
    req.mkdir(parents=True, exist_ok=True)
    resp.mkdir(parents=True, exist_ok=True)
    return req, resp


def _agent(system: str, user: str, schema: dict, schema_name: str) -> dict:
    """Same prompt and schema as the API path; the answer is written by a Claude Code agent.
    Answers are validated against the schema before they are accepted."""
    import jsonschema
    key = hashlib.sha256(json.dumps([AGENT_MODEL, system, user, schema], sort_keys=True).encode()).hexdigest()[:24]
    req, resp = agent_dirs()
    out = resp / f"{key}.json"
    if out.exists():
        try:
            data = json.loads(out.read_text())
            jsonschema.validate(data, schema)
            return data
        except (json.JSONDecodeError, jsonschema.ValidationError) as e:
            out.rename(out.with_suffix(".invalid.json"))  # keep for inspection, ask again
            (req / f"{key}.error.txt").write_text(str(e)[:2000])
    (req / f"{key}.json").write_text(json.dumps(
        {"key": key, "schema_name": schema_name, "system": system, "user": user, "schema": schema,
         "response_path": str(out)}, indent=1))
    raise LLMPending(f"queued {schema_name} request {key} for an agent")


def set_fake(fn: Callable[[str, str, str], dict] | None):
    global _fake
    _fake = fn


def _cache_path(key: str):
    d = config.CACHE_DIR / "llm"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{key}.json"


def complete_json(system: str, user: str, schema: dict, schema_name: str, *, mode: str | None = None) -> dict:
    mode = mode or config.LLM_MODE
    if mode == "agent":
        return _agent(system, user, schema, schema_name)
    if mode == "fake":
        if _fake is None:
            raise LLMError("fake LLM mode without a fake installed")
        return _fake(system, user, schema_name)

    key = hashlib.sha256(json.dumps([config.LLM_MODEL, config.LLM_EFFORT, system, user, schema],
                                    sort_keys=True).encode()).hexdigest()
    path = _cache_path(key)
    if path.exists():
        return json.loads(path.read_text())["output"]
    if mode == "replay":
        raise LLMError(f"replay cache miss for {schema_name} ({key[:12]})")

    import anthropic  # imported lazily so tests and replay never need credentials

    client = anthropic.Anthropic()
    try:
        with client.messages.stream(
            model=config.LLM_MODEL,
            max_tokens=64000,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
            output_config={"effort": config.LLM_EFFORT,
                           "format": {"type": "json_schema", "schema": schema}},
            extra_headers={"anthropic-beta": "server-side-fallback-2026-07-01"},
            extra_body={"fallbacks": "default"},
        ) as stream:
            msg = stream.get_final_message()
    except anthropic.RateLimitError as e:
        raise LLMError(f"rate limited: {e}") from e
    except anthropic.APIStatusError as e:
        raise LLMError(f"API error {e.status_code}: {e}") from e
    except anthropic.APIConnectionError as e:
        raise LLMError(f"connection error: {e}") from e

    if msg.stop_reason == "refusal":
        raise LLMError(f"refusal on {schema_name}: {getattr(msg, 'stop_details', None)}")
    if msg.stop_reason == "max_tokens":
        raise LLMError(f"output truncated on {schema_name}")
    text = next((b.text for b in msg.content if b.type == "text"), None)
    if text is None:
        raise LLMError(f"no text block for {schema_name}")
    output = json.loads(text)
    path.write_text(json.dumps({
        "model": msg.model, "schema": schema_name, "prompt_version": config.PROMPT_VERSION,
        "usage": msg.usage.model_dump() if hasattr(msg.usage, "model_dump") else None,
        "output": output,
    }, indent=1))
    return output
