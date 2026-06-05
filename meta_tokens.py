"""Meta/Threads/Instagram/Facebook token validation and refresh helpers."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from http_utils import HttpClient, response_json_or_raise, summarize_response
from runtime_config import FacebookConfig, InstagramConfig, ThreadsConfig
from structured_logging import log_event


# ---------------------------------------------------------------------------
# Shared result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class TokenValidationResult:
    valid: bool
    status: str
    user_id: str = ""
    username: str = ""
    expires_in: int | None = None   # seconds until expiry, if reported by API
    error: str = ""


@dataclass
class TokenRefreshResult:
    success: bool
    status: str
    access_token: str = ""
    expires_in: int | None = None
    error: str = ""


# ---------------------------------------------------------------------------
# Threads
# ---------------------------------------------------------------------------

def validate_threads_token(
    config: ThreadsConfig,
    http: HttpClient,
    logger: logging.Logger | None = None,
) -> TokenValidationResult:
    if not config.access_token:
        result = TokenValidationResult(False, "missing_token", error="THREADS_ACCESS_TOKEN is not configured")
        _log_validation(logger, "threads_token_validation_failed", result, "threads")
        return result
    if not config.user_id:
        result = TokenValidationResult(False, "missing_user_id", error="THREADS_USER_ID is not configured")
        _log_validation(logger, "threads_token_validation_failed", result, "threads")
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
        _log_validation(logger, "threads_token_validation_failed", result, "threads")
        return result

    result = TokenValidationResult(True, "valid", user_id=returned_id, username=username)
    _log_validation(logger, "threads_token_validation_succeeded", result, "threads")
    return result


def refresh_threads_token(
    config: ThreadsConfig,
    http: HttpClient,
    logger: logging.Logger | None = None,
) -> TokenRefreshResult:
    if not config.access_token:
        result = TokenRefreshResult(False, "missing_token", error="THREADS_ACCESS_TOKEN is not configured")
        _log_refresh(logger, "threads_token_refresh_failed", result, "threads")
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
        result = TokenRefreshResult(
            False, "missing_access_token",
            error=f"Refresh response did not contain access_token: {summarize_response(response)}",
        )
        _log_refresh(logger, "threads_token_refresh_failed", result, "threads")
        return result

    result = TokenRefreshResult(True, "refreshed", access_token=new_token, expires_in=data.get("expires_in"))
    _log_refresh(logger, "threads_token_refresh_succeeded", result, "threads")
    return result


# ---------------------------------------------------------------------------
# Instagram
# ---------------------------------------------------------------------------

def validate_instagram_token(
    config: InstagramConfig,
    http: HttpClient,
    logger: logging.Logger | None = None,
) -> TokenValidationResult:
    """Validate IG_TOKEN by calling the Instagram Graph API /me endpoint."""
    if not config.access_token:
        result = TokenValidationResult(False, "missing_token", error="IG_TOKEN is not configured")
        _log_validation(logger, "instagram_token_validation_failed", result, "instagram")
        return result

    # Business/Creator accounts use graph.facebook.com, not graph.instagram.com.
    # graph.instagram.com is for Basic Display API (personal accounts only).
    base_url = (
        f"https://graph.facebook.com/{config.api_version}/{config.user_id}"
        if config.user_id
        else f"https://graph.facebook.com/{config.api_version}/me"
    )
    url = base_url
    try:
        response = http.get(
            url,
            params={"fields": "id,username,name", "access_token": config.access_token},
            platform="instagram",
        )
        data = response_json_or_raise(response, "INSTAGRAM TOKEN VALIDATION")
    except Exception as exc:
        result = TokenValidationResult(False, "request_failed", error=str(exc))
        if logger:
            log_event(logger, "instagram_token_validation_failed", logging.WARNING, platform="instagram", status=result.status, error=str(exc))
        return result

    returned_id = str(data.get("id", ""))
    username = str(data.get("username", ""))

    # If IG_USER_ID is configured, cross-check it; otherwise just require a returned id.
    if config.user_id and returned_id != str(config.user_id):
        result = TokenValidationResult(
            False,
            "user_id_mismatch",
            user_id=returned_id,
            username=username,
            error="Instagram token user id does not match IG_USER_ID",
        )
        _log_validation(logger, "instagram_token_validation_failed", result, "instagram")
        return result

    if not returned_id:
        result = TokenValidationResult(False, "empty_user_id", error="Instagram API returned no user id")
        _log_validation(logger, "instagram_token_validation_failed", result, "instagram")
        return result

    result = TokenValidationResult(True, "valid", user_id=returned_id, username=username)
    _log_validation(logger, "instagram_token_validation_succeeded", result, "instagram")
    return result


def refresh_instagram_token(
    config: InstagramConfig,
    http: HttpClient,
    logger: logging.Logger | None = None,
) -> TokenRefreshResult:
    """Refresh a long-lived Instagram token. Valid for another 60 days after refresh."""
    if not config.access_token:
        result = TokenRefreshResult(False, "missing_token", error="IG_TOKEN is not configured")
        _log_refresh(logger, "instagram_token_refresh_failed", result, "instagram")
        return result

    try:
        response = http.get(
            "https://graph.instagram.com/refresh_access_token",
            params={"grant_type": "ig_refresh_token", "access_token": config.access_token},
            platform="instagram",
        )
        data = response_json_or_raise(response, "INSTAGRAM TOKEN REFRESH")
    except Exception as exc:
        result = TokenRefreshResult(False, "request_failed", error=str(exc))
        if logger:
            log_event(logger, "instagram_token_refresh_failed", logging.WARNING, platform="instagram", status=result.status, error=str(exc))
        return result

    new_token = str(data.get("access_token", ""))
    if not new_token:
        result = TokenRefreshResult(
            False, "missing_access_token",
            error=f"Refresh response did not contain access_token: {summarize_response(response)}",
        )
        _log_refresh(logger, "instagram_token_refresh_failed", result, "instagram")
        return result

    result = TokenRefreshResult(True, "refreshed", access_token=new_token, expires_in=data.get("expires_in"))
    _log_refresh(logger, "instagram_token_refresh_succeeded", result, "instagram")
    return result


# ---------------------------------------------------------------------------
# Facebook
# ---------------------------------------------------------------------------

def validate_facebook_token(
    config: FacebookConfig,
    http: HttpClient,
    logger: logging.Logger | None = None,
) -> TokenValidationResult:
    """
    Validate FB_PAGE_TOKEN via the Graph API debug_token endpoint.

    Requires FACEBOOK_APP_ID and FACEBOOK_APP_SECRET (stored as GitHub Secrets).
    Falls back to a lightweight /me call if app credentials are unavailable.
    """
    if not config.page_token:
        result = TokenValidationResult(False, "missing_token", error="FB_PAGE_TOKEN is not configured")
        _log_validation(logger, "facebook_token_validation_failed", result, "facebook")
        return result

    # Prefer debug_token (gives expiry info) when app credentials are available
    if config.app_id and config.app_secret:
        return _validate_facebook_debug_token(config, http, logger)
    else:
        return _validate_facebook_me(config, http, logger)


def _validate_facebook_debug_token(
    config: FacebookConfig,
    http: HttpClient,
    logger: logging.Logger | None = None,
) -> TokenValidationResult:
    """Use /debug_token for rich validation including expiry and scope info."""
    app_access_token = f"{config.app_id}|{config.app_secret}"
    try:
        response = http.get(
            f"https://graph.facebook.com/{config.api_version}/debug_token",
            params={"input_token": config.page_token, "access_token": app_access_token},
            platform="facebook",
        )
        data = response_json_or_raise(response, "FACEBOOK TOKEN DEBUG")
    except Exception as exc:
        result = TokenValidationResult(False, "request_failed", error=str(exc))
        if logger:
            log_event(logger, "facebook_token_validation_failed", logging.WARNING, platform="facebook", status=result.status, error=str(exc))
        return result

    token_data = data.get("data", {})
    is_valid = bool(token_data.get("is_valid", False))
    expires_at = token_data.get("expires_at", 0)  # 0 means never expires
    user_id = str(token_data.get("user_id", ""))
    scopes = token_data.get("scopes", [])

    # expires_at == 0 → never-expiring page token (correct)
    expires_in = None
    if expires_at and expires_at > 0:
        import time
        expires_in = max(0, int(expires_at - time.time()))

    if not is_valid:
        error_subcode = token_data.get("error", {}).get("message", "token invalid")
        result = TokenValidationResult(
            False, "token_invalid",
            user_id=user_id,
            expires_in=expires_in,
            error=error_subcode,
        )
        _log_validation(logger, "facebook_token_validation_failed", result, "facebook")
        return result

    result = TokenValidationResult(
        True, "valid",
        user_id=user_id,
        expires_in=expires_in,
    )
    if logger:
        log_event(
            logger, "facebook_token_validation_succeeded", logging.INFO,
            platform="facebook", status="valid",
            details={"user_id": user_id, "expires_at": expires_at, "scopes": scopes, "expires_in": expires_in},
        )
    return result


def _validate_facebook_me(
    config: FacebookConfig,
    http: HttpClient,
    logger: logging.Logger | None = None,
) -> TokenValidationResult:
    """Lightweight fallback: call /me when app credentials are not available."""
    if logger:
        log_event(
            logger, "facebook_token_validation_fallback", logging.WARNING, platform="facebook",
            status="fallback",
            details={"reason": "FACEBOOK_APP_ID or FACEBOOK_APP_SECRET not configured; using /me fallback (no expiry info)"},
        )
    try:
        response = http.get(
            f"https://graph.facebook.com/{config.api_version}/me",
            params={"fields": "id,name", "access_token": config.page_token},
            platform="facebook",
        )
        data = response_json_or_raise(response, "FACEBOOK TOKEN ME")
    except Exception as exc:
        result = TokenValidationResult(False, "request_failed", error=str(exc))
        if logger:
            log_event(logger, "facebook_token_validation_failed", logging.WARNING, platform="facebook", status=result.status, error=str(exc))
        return result

    page_id = str(data.get("id", ""))
    name = str(data.get("name", ""))
    if not page_id:
        result = TokenValidationResult(False, "empty_page_id", error="Facebook API returned no page id")
        _log_validation(logger, "facebook_token_validation_failed", result, "facebook")
        return result

    result = TokenValidationResult(True, "valid", user_id=page_id, username=name)
    _log_validation(logger, "facebook_token_validation_succeeded", result, "facebook")
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _log_validation(
    logger: logging.Logger | None,
    event: str,
    result: TokenValidationResult,
    platform: str,
) -> None:
    if not logger:
        return
    log_event(
        logger,
        event,
        logging.INFO if result.valid else logging.WARNING,
        platform=platform,
        status=result.status,
        error=result.error or None,
        details={
            "user_id": result.user_id,
            "username": result.username,
            "expires_in": result.expires_in,
        } if result.valid else None,
    )


def _log_refresh(
    logger: logging.Logger | None,
    event: str,
    result: TokenRefreshResult,
    platform: str,
) -> None:
    if not logger:
        return
    log_event(
        logger,
        event,
        logging.INFO if result.success else logging.WARNING,
        platform=platform,
        status=result.status,
        error=result.error or None,
        details={"expires_in": result.expires_in} if result.success else None,
    )
