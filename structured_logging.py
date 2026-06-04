"""Centralized structured JSON logging with secret redaction."""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOG_DIR = Path(os.getenv("LOG_DIR", "logs"))
_TOKEN_PATTERNS = [
    re.compile(r"([?&](?:access_)?token=)[^&\s]+", re.IGNORECASE),
    re.compile(r"(access_token['\"\s:=]+)[^,'\"\s}]+", re.IGNORECASE),
    re.compile(r"((?:IG|FB|WIX|OPENAI|CLOUDINARY|THREADS)[A-Z_]*(?:TOKEN|KEY|SECRET)['\"\s:=]+)[^,'\"\s}]+", re.IGNORECASE),
]


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if any(s in k.lower() for s in ("token", "secret", "key")) else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if not isinstance(value, str):
        return value
    redacted = value
    for pattern in _TOKEN_PATTERNS:
        redacted = pattern.sub(r"\1[REDACTED]", redacted)
    return redacted


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "module": record.name,
            "event": getattr(record, "event", record.getMessage()),
            "severity": record.levelname,
            "platform": getattr(record, "platform", None),
            "status": getattr(record, "status", None),
            "record_id": getattr(record, "record_id", None),
            "message": record.getMessage(),
        }
        for attr in ("error", "response_summary", "details"):
            value = getattr(record, attr, None)
            if value is not None:
                payload[attr] = redact(value)
        return json.dumps({k: v for k, v in payload.items() if v is not None}, ensure_ascii=False)


def get_logger(name: str) -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(name)
    logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))
    logger.propagate = False
    if not logger.handlers:
        formatter = JsonFormatter()
        stream = logging.StreamHandler(sys.stdout)
        stream.setFormatter(formatter)
        file_handler = logging.FileHandler(LOG_DIR / "pipeline.jsonl", encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(stream)
        logger.addHandler(file_handler)
    return logger


def log_event(logger: logging.Logger, event: str, severity: int = logging.INFO, **kwargs: Any) -> None:
    logger.log(severity, event, extra={"event": event, **kwargs})
