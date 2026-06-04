"""Reusable HTTP client with retry, backoff, timeout, and safe summaries."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import requests

from runtime_config import FeatureFlags
from structured_logging import log_event, redact

RETRY_STATUSES = {429, 500, 502, 503, 504}


class HttpRequestError(Exception):
    def __init__(self, message: str, response: requests.Response | None = None):
        self.response = response
        super().__init__(message)


@dataclass
class HttpClient:
    max_retries: int = 3
    timeout: int = 30
    backoff_base: float = 1.0
    logger: logging.Logger | None = None

    @classmethod
    def from_flags(cls, flags: FeatureFlags, logger: logging.Logger | None = None) -> "HttpClient":
        return cls(max_retries=flags.http_max_retries, timeout=flags.http_timeout_seconds, logger=logger)

    def request(self, method: str, url: str, *, platform: str | None = None, **kwargs: Any) -> requests.Response:
        kwargs.setdefault("timeout", self.timeout)
        for attempt in range(1, self.max_retries + 1):
            try:
                response = requests.request(method, url, **kwargs)
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    raise HttpRequestError(f"HTTP {method} {url} failed after {attempt} attempts: {exc}") from exc
                self._log_retry(method, url, attempt, platform, error=str(exc))
                time.sleep(self.backoff_base * (2 ** (attempt - 1)))
                continue

            if response.status_code not in RETRY_STATUSES or attempt >= self.max_retries:
                return response

            self._log_retry(method, url, attempt, platform, response=response)
            time.sleep(self.backoff_base * (2 ** (attempt - 1)))
        raise HttpRequestError(f"HTTP {method} {url} failed unexpectedly")

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> requests.Response:
        return self.request("POST", url, **kwargs)

    def _log_retry(self, method: str, url: str, attempt: int, platform: str | None, **kwargs: Any) -> None:
        if not self.logger:
            return
        response = kwargs.get("response")
        summary = summarize_response(response) if response is not None else None
        log_event(
            self.logger,
            "http_retry_scheduled",
            severity=logging.WARNING,
            platform=platform,
            status="retrying",
            details={"method": method, "url": redact(url), "attempt": attempt, "response": summary, "error": kwargs.get("error")},
        )


def summarize_response(response: requests.Response | None) -> dict[str, Any] | None:
    if response is None:
        return None
    body = response.text[:500] if response.text else ""
    return redact({"status_code": response.status_code, "body": body})


def response_json_or_raise(response: requests.Response, step_name: str, expected: tuple[int, ...] = (200, 201)) -> dict[str, Any]:
    if response.status_code not in expected:
        raise HttpRequestError(f"[{step_name}] HTTP {response.status_code}: {response.text[:500]}", response=response)
    try:
        return response.json()
    except ValueError as exc:
        raise HttpRequestError(f"[{step_name}] Non-JSON response: {response.text[:200]}", response=response) from exc
