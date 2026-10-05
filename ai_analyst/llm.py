"""Claude client wrapper (Anthropic Python SDK).

* Model: Claude Opus 5.5 (``claude-opus-5-5``) by default; override with AI_ANALYST_MODEL.
* Thinking is adaptive (always on for this model); depth is controlled with ``output_config.effort``.
* Structured outputs (``output_config.format`` with a JSON schema) guarantee parseable JSON.
* Server-side refusal fallback is enabled (``fallbacks: "default"`` + beta header) so a policy
  decline is retried on a suitable model inside the same call.
* Credentials: ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN or an ``ant auth login`` profile - the SDK
  resolves them; if none work we raise LLMUnavailable and callers fall back to deterministic logic.

Parameters newer than the SDK release shipped for Python 3.8 are passed through ``extra_body`` /
``extra_headers``, which the SDK forwards unchanged.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

MODEL = os.getenv("AI_ANALYST_MODEL", "claude-opus-5-5")
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMUnavailable(Exception):
    """Raised when the model cannot be used (no SDK, no credentials, network, refusal, ...)."""


def _client():
    try:
        import anthropic  # noqa: F401
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise LLMUnavailable("the 'anthropic' package is not installed") from exc
    import anthropic
    return anthropic.Anthropic(max_retries=3, timeout=600.0)


def block_to_dict(block: Any) -> Dict:
    """Serialise a response content block faithfully (thinking blocks must be passed back unchanged)."""
    for attr in ("to_dict", "model_dump"):
        fn = getattr(block, attr, None)
        if fn is not None:
            try:
                return fn(exclude_unset=True) if attr == "model_dump" else fn()
            except TypeError:
                return fn()
    return dict(block)


def text_of(content: List[Dict]) -> str:
    return "".join(b.get("text", "") for b in content if b.get("type") == "text")


def create_message(system: List[Dict], messages: List[Dict], json_schema: Optional[Dict] = None,
                   tools: Optional[List[Dict]] = None, effort: str = "medium", max_tokens: int = 16000) -> Dict:
    """One Messages API call. Returns {"content": [...dicts], "stop_reason": str, "usage": {...}, "model": str}."""
    client = _client()  # first, so a missing SDK becomes LLMUnavailable rather than an ImportError
    import anthropic

    output_config: Dict[str, Any] = {"effort": effort}
    if json_schema:
        output_config["format"] = {"type": "json_schema", "schema": json_schema}
    kwargs: Dict[str, Any] = {
        "model": MODEL, "max_tokens": max_tokens, "system": system, "messages": messages,
        "extra_headers": {"anthropic-beta": FALLBACK_BETA},
        "extra_body": {"output_config": output_config, "fallbacks": "default"},
    }
    if tools:
        kwargs["tools"] = tools
    try:
        resp = client.messages.create(**kwargs)
    except anthropic.AuthenticationError as exc:
        raise LLMUnavailable("authentication failed - set ANTHROPIC_API_KEY or run `ant auth login`") from exc
    except anthropic.PermissionDeniedError as exc:
        raise LLMUnavailable("credentials lack permission for model %s" % MODEL) from exc
    except anthropic.NotFoundError as exc:
        raise LLMUnavailable("model %s not found for this account" % MODEL) from exc
    except anthropic.RateLimitError as exc:
        raise LLMUnavailable("rate limited after retries") from exc
    except anthropic.BadRequestError:
        raise  # a malformed request is a bug in our code - surface it
    except anthropic.APIStatusError as exc:
        raise LLMUnavailable("API error %s" % getattr(exc, "status_code", "?")) from exc
    except anthropic.APIConnectionError as exc:
        raise LLMUnavailable("network error reaching the Claude API") from exc
    except TypeError as exc:
        # With no API key, auth token or login profile the SDK fails while building the request, before
        # any HTTP call (e.g. in CI when the ANTHROPIC_API_KEY secret is missing and arrives as "").
        if "authentication" in str(exc).lower():
            raise LLMUnavailable("no Claude credentials - set ANTHROPIC_API_KEY or run `ant auth login`") from exc
        raise

    stop = getattr(resp, "stop_reason", None)
    if stop == "refusal":
        details = getattr(resp, "stop_details", None)
        raise LLMUnavailable("model declined the request (%s)" % getattr(details, "category", "unspecified"))
    if stop == "max_tokens":
        raise LLMUnavailable("response truncated at max_tokens")
    usage = getattr(resp, "usage", None)
    return {"content": [block_to_dict(b) for b in resp.content], "stop_reason": stop,
            "model": getattr(resp, "model", MODEL), "request_id": getattr(resp, "_request_id", None),
            "usage": {"input_tokens": getattr(usage, "input_tokens", None),
                      "output_tokens": getattr(usage, "output_tokens", None),
                      "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", None)}}
