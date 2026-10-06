"""Structured JSON logging with a correlation_id carried through each message."""

import json
import logging
import sys
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone

correlation_id: ContextVar[str] = ContextVar("correlation_id", default="-")

# Keys never written to logs, whatever their value.
_MASKED_KEYS = {"access_token", "api_key", "authorization", "password", "otp", "secret", "token"}


def new_correlation_id() -> str:
    cid = uuid.uuid4().hex[:16]
    correlation_id.set(cid)
    return cid


def _mask(value: object) -> object:
    if isinstance(value, dict):
        return {k: ("***" if k.lower() in _MASKED_KEYS else _mask(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask(v) for v in value]
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "correlation_id": correlation_id.get(),
        }
        extra = getattr(record, "data", None)
        if isinstance(extra, dict):
            payload["data"] = _mask(extra)
        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
