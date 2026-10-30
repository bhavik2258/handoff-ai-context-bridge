import contextvars
import json
import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


request_id_context: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)

_API_KEY_PATTERN = re.compile(
    r"(?i)(\b(?:api[_-]?key|x-api-key|authorization|bearer|token)\b"
    r"\s*[:=]\s*['\"]?)([A-Za-z0-9._~+/=-]{8,})"
)
_SECRET_PATTERN = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{8,}|AIza[A-Za-z0-9_-]{20,})\b")


def redact(value: Any) -> Any:
    if isinstance(value, str):
        redacted = _API_KEY_PATTERN.sub(r"\1[REDACTED]", value)
        return _SECRET_PATTERN.sub("[REDACTED]", redacted)
    if isinstance(value, dict):
        return {key: redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    return value


class RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.msg)
        if record.args:
            record.args = redact(record.args)
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
            "request_id": request_id_context.get(),
        }
        for field in ("event", "method", "path", "status", "duration_ms"):
            if hasattr(record, field):
                payload[field] = getattr(record, field)
        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=True)


def configure_logging() -> None:
    log_path = Path("logs/app.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    formatter = JsonFormatter()
    redaction_filter = RedactionFilter()
    handlers: list[logging.Handler] = [
        logging.StreamHandler(),
        RotatingFileHandler(log_path, maxBytes=5_000_000, backupCount=3),
    ]
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()
    for handler in handlers:
        handler.setFormatter(formatter)
        handler.addFilter(redaction_filter)
        root_logger.addHandler(handler)
