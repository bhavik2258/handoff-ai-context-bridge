from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
import anthropic
import pytest
from pydantic import BaseModel

from app.services.ai_client import AIUnavailableError, call_ai_json


class Result(BaseModel):
    answer: str


def response(text: str, input_tokens: int = 3, output_tokens: int = 2):
    return SimpleNamespace(
        content=[SimpleNamespace(text=text)],
        usage=SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        ),
    )


def test_call_ai_json_success(monkeypatch):
    client = Mock()
    client.messages.create.return_value = response('{"answer":"ok"}')
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("AI_MODEL", "test-model")
    from app.config import get_settings

    get_settings.cache_clear()
    with patch("app.services.ai_client.anthropic.Anthropic", return_value=client):
        result = call_ai_json("test", "system", "user", Result)
    assert result.answer == "ok"


def test_call_ai_json_repairs_bad_json(monkeypatch):
    client = Mock()
    client.messages.create.side_effect = [
        response("not json"),
        response("```json\n{\"answer\":\"repaired\"}\n```"),
    ]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    from app.config import get_settings

    get_settings.cache_clear()
    with patch("app.services.ai_client.anthropic.Anthropic", return_value=client):
        result = call_ai_json("test", "system", "user", Result)
    assert result.answer == "repaired"
    assert client.messages.create.call_count == 2


def test_call_ai_json_repeated_api_failure_raises(monkeypatch):
    client = Mock()
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    client.messages.create.side_effect = anthropic.APIConnectionError(
        message="provider down", request=request
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    from app.config import get_settings

    get_settings.cache_clear()
    with (
        patch("app.services.ai_client.anthropic.Anthropic", return_value=client),
        patch("app.services.ai_client.time.sleep"),
    ):
        with pytest.raises(AIUnavailableError):
            call_ai_json("test", "system", "user", Result)


def test_call_ai_json_without_key_fails_immediately(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from app.config import get_settings

    get_settings.cache_clear()
    with patch("app.services.ai_client.anthropic.Anthropic") as anthropic_client:
        with pytest.raises(AIUnavailableError):
            call_ai_json("test", "system", "user", Result)
    anthropic_client.assert_not_called()
