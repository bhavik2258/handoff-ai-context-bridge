import json
import logging
import time
from typing import Any, TypeVar

import anthropic
import httpx
from pydantic import BaseModel

from ..config import get_settings


logger = logging.getLogger(__name__)
ModelT = TypeVar("ModelT", bound=BaseModel)


class AIUnavailableError(Exception):
    """Raised when the AI provider cannot return a validated response."""


def _response_text(response: Any) -> str:
    return response.content[0].text


def _usage(response: Any) -> tuple[int | None, int | None]:
    usage = getattr(response, "usage", None)
    return (
        getattr(usage, "input_tokens", None),
        getattr(usage, "output_tokens", None),
    )


def _parse_response(response: Any, model: type[ModelT]) -> ModelT:
    text = _response_text(response).strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].strip().lower() in {"```json", "```"}:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return model.model_validate(json.loads(text))


def _create_message(client: anthropic.Anthropic, system_prompt: str, user_prompt: str) -> Any:
    return client.messages.create(
        model=get_settings().ai_model,
        max_tokens=2048,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )


def call_ai_json(
    feature: str,
    system_prompt: str,
    user_prompt: str,
    pydantic_model: type[ModelT],
) -> ModelT:
    started = time.perf_counter()
    outcome = "failed"
    input_tokens: int | None = None
    output_tokens: int | None = None
    settings = get_settings()
    if not settings.anthropic_api_key:
        _log_call(feature, started, outcome, input_tokens, output_tokens)
        raise AIUnavailableError("AI provider is not configured")

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=20.0)
    try:
        try:
            response = _create_message(client, system_prompt, user_prompt)
        except (anthropic.APIError, httpx.TimeoutException, TimeoutError):
            time.sleep(1)
            try:
                response = _create_message(client, system_prompt, user_prompt)
                outcome = "retried"
            except (anthropic.APIError, httpx.TimeoutException, TimeoutError) as second_error:
                raise AIUnavailableError("AI provider request failed") from second_error

        input_tokens, output_tokens = _usage(response)
        try:
            result = _parse_response(response, pydantic_model)
            if outcome != "retried":
                outcome = "success"
            return result
        except (IndexError, json.JSONDecodeError, TypeError, ValueError) as parse_error:
            repair_prompt = (
                f"{user_prompt}\n\nThe previous response was invalid: {parse_error}. "
                "Return valid JSON only, matching the requested schema."
            )
            try:
                repaired_response = _create_message(client, system_prompt, repair_prompt)
                input_tokens, output_tokens = _usage(repaired_response)
                result = _parse_response(repaired_response, pydantic_model)
                outcome = "repaired"
                return result
            except (
                anthropic.APIError,
                httpx.TimeoutException,
                TimeoutError,
                json.JSONDecodeError,
                IndexError,
                TypeError,
                ValueError,
            ) as repair_error:
                raise AIUnavailableError("AI provider returned invalid JSON") from repair_error
    finally:
        _log_call(feature, started, outcome, input_tokens, output_tokens)


def _log_call(
    feature: str,
    started: float,
    outcome: str,
    input_tokens: int | None,
    output_tokens: int | None,
) -> None:
    logger.info(
        "ai.call",
        extra={
            "event": "ai.call",
            "provider": "anthropic",
            "model": get_settings().ai_model,
            "feature": feature,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "outcome": outcome,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        },
    )
