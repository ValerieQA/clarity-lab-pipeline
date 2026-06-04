"""Meta/Threads token validation and refresh helpers."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from http_utils import HttpClient, response_json_or_raise, summarize_response
from runtime_config import ThreadsConfig
from structured_logging import log_event


@dataclass
class TokenValidationResult:
    valid: bool
    status: str
    user_id: str = ""
    username: str = ""
    error: str = ""


@dataclass
class TokenRefreshResult:
    success: bool
    status: str
    access_token: str = ""
    expires_in: int | None = None
    error: str = ""


def validate_threads_token(config: ThreadsConfig, http: HttpClient, logger: logging.Logger | None = None) -> TokenValidationResult:
    if not config.access_token:
        result = TokenValidationResult(False, "missing_token", error="THREADS_ACCESS_TOKEN is not configured")
        _log(logger, "threads_token_validation_failed", result)
        return result
    if not config.user_id:
        result = TokenValidationResult(False, "missing_user_id", error="THREADS_USER_ID is not configured")
        _log(logger, "threads_token_validation_failed", result)
        return result

    url = f"https://graph.threads.net/{config.api_version}/me"
    try:
        response = http.get(
            url,
            params={"fields": "id,username", "access_token": config.access_token},
            platform="threads",
        )
        data = response_json_or_raise(response, "THREADS TOKEN VALIDATION")
    except Exception as exc:
        result = TokenValidationResult(False, "request_failed", error=str(exc))
        if logger:
            log_event(logger, "threads_token_validation_failed", logging.WARNING, platform="threads", status=result.status, error=str(exc))
        return result

    returned_id = str(data.get("id", ""))
    username = str(data.get("username", ""))
    if returned_id != str(config.user_id):
        result = TokenValidationResult(
            False,
            "user_id_mismatch",
            user_id=returned_id,
            username=username,
            error="Threads token user id does not match THREADS_USER_ID",
        )
        _log(logger, "threads_token_validation_failed", result)
        return result

    result = TokenValidationResult(True, "valid", user_id=returned_id, username=username)
    _log(logger, "threads_token_validation_succeeded", result)
    return result


def refresh_threads_token(config: ThreadsConfig, http: HttpClient, logger: logging.Logger | None = None) -> TokenRefreshResult:
    if not config.access_token:
        result = TokenRefreshResult(False, "missing_token", error="THREADS_ACCESS_TOKEN is not configured")
        _log_refresh(logger, "threads_token_refresh_failed", result)
        return result

    try:
        response = http.get(
            "https://graph.threads.net/refresh_access_token",
            params={"grant_type": "th_refresh_token", "access_token": config.access_token},
            platform="threads",
        )
        data = response_json_or_raise(response, "THREADS TOKEN REFRESH")
    except Exception as exc:
        result = TokenRefreshResult(False, "request_failed", error=str(exc))
        if logger:
            log_event(logger, "threads_token_refresh_failed", logging.WARNING, platform="threads", status=result.status, error=str(exc))
        return result

    new_token = str(data.get("access_token", ""))
    if not new_token:
        result = TokenRefreshResult(False, "missing_access_token", error=f"Refresh response did not contain access_token: {summarize_response(response)}")
        _log_refresh(logger, "threads_token_refresh_failed", result)
        return result

    result = TokenRefreshResult(True, "refreshed", access_token=new_token, expires_in=data.get("expires_in"))
    _log_refresh(logger, "threads_token_refresh_succeeded", result)
    return result


def _log(logger: logging.Logger | None, event: str, result: TokenValidationResult) -> None:
    if logger:
        log_event(
            logger,
            event,
            logging.INFO if result.valid else logging.WARNING,
            platform="threads",
            status=result.status,
            error=result.error or None,
            details={"user_id": result.user_id, "username": result.username} if result.valid else None,
        )


def _log_refresh(logger: logging.Logger | None, event: str, result: TokenRefreshResult) -> None:
    if logger:
        log_event(
            logger,
            event,
            logging.INFO if result.success else logging.WARNING,
            platform="threads",
            status=result.status,
            error=result.error or None,
            details={"expires_in": result.expires_in} if result.success else None,
        )
