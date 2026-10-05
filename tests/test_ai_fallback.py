"""The AI layer must fall back to the deterministic summary when Claude can't be used (e.g. CI without a key)."""
import sys
import types

import pytest

from ai_analyst import llm
from ai_analyst.llm import LLMUnavailable
from ai_analyst.summarizer import generate_summary

# What the real SDK raises while building a request when no API key, auth token or login profile resolves.
MISSING_CREDENTIALS = TypeError(
    '"Could not resolve authentication method. Expected one of api_key, auth_token, or credentials to be set."')


def _fake_sdk(create_error):
    """A stand-in `anthropic` module whose messages.create raises `create_error`."""
    sdk = types.ModuleType("anthropic")
    for name in ("AuthenticationError", "PermissionDeniedError", "NotFoundError", "RateLimitError",
                 "BadRequestError", "APIStatusError", "APIConnectionError"):
        setattr(sdk, name, type(name, (Exception,), {}))

    class Messages:
        def create(self, **kwargs):
            raise create_error

    class Anthropic:
        def __init__(self, **kwargs):
            self.messages = Messages()

    sdk.Anthropic = Anthropic
    return sdk


def test_missing_sdk_is_unavailable(monkeypatch):
    monkeypatch.setitem(sys.modules, "anthropic", None)  # makes `import anthropic` raise ImportError
    with pytest.raises(LLMUnavailable, match="not installed"):
        llm.create_message(system=[], messages=[])


def test_missing_credentials_is_unavailable(monkeypatch):
    monkeypatch.setitem(sys.modules, "anthropic", _fake_sdk(MISSING_CREDENTIALS))
    with pytest.raises(LLMUnavailable, match="no Claude credentials"):
        llm.create_message(system=[], messages=[])


def test_unrelated_type_errors_still_surface(monkeypatch):
    monkeypatch.setitem(sys.modules, "anthropic", _fake_sdk(TypeError("unexpected keyword argument 'foo'")))
    with pytest.raises(TypeError, match="unexpected keyword"):
        llm.create_message(system=[], messages=[])


def test_summary_falls_back_without_credentials(e2e, monkeypatch):
    monkeypatch.setitem(sys.modules, "anthropic", _fake_sdk(MISSING_CREDENTIALS))
    res = generate_summary(e2e["settings"], offline=False)
    assert res["mode"] == "deterministic"
    assert "no Claude credentials" in res["note"]
    assert res["validation"]["grounded"]
