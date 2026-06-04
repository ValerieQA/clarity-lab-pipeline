#!/usr/bin/env python3
"""
Unified Meta token health check.

For each platform:
  1. Validate the current token.
  2. If invalid → exit 1 (caller creates a GitHub Issue alert).
  3. If valid and expiring within REFRESH_THRESHOLD_DAYS → refresh.
  4. Validate the refreshed token before writing it to GitHub Secrets.
  5. Update the GitHub Secret via update_github_secret.py.

Usage:
    python scripts/token_health_check.py --platform threads
    python scripts/token_health_check.py --platform instagram
    python scripts/token_health_check.py --platform facebook

Exit codes:
    0   Token is valid (and refreshed if needed).
    1   Token is invalid or health check failed — trigger an alert.
    2   Refresh succeeded but GitHub Secret update failed (alert required).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from http_utils import HttpClient
from meta_tokens import (
    refresh_instagram_token,
    refresh_threads_token,
    validate_facebook_token,
    validate_instagram_token,
    validate_threads_token,
)
from runtime_config import FacebookConfig, FeatureFlags, InstagramConfig, ThreadsConfig
from scripts.update_github_secret import update_github_secret
from structured_logging import get_logger

# Tokens expiring within this many days are proactively refreshed.
REFRESH_THRESHOLD_DAYS = 14
REFRESH_THRESHOLD_SECONDS = REFRESH_THRESHOLD_DAYS * 86_400


def _needs_refresh(expires_in: int | None) -> bool:
    """Return True if token expires within the threshold window."""
    if expires_in is None:
        # Cannot determine — refresh proactively to be safe.
        return True
    return expires_in < REFRESH_THRESHOLD_SECONDS


def check_threads(flags: FeatureFlags, http: HttpClient) -> int:
    logger = get_logger("token_health.threads")
    config = ThreadsConfig.from_env()

    print("[THREADS] Validating token...")
    result = validate_threads_token(config, http, logger)
    if not result.valid:
        print(f"[THREADS] Token INVALID: {result.status} — {result.error}")
        return 1

    expires_in = result.expires_in
    print(f"[THREADS] Token valid (user={result.username}, expires_in={expires_in}s).")

    if not _needs_refresh(expires_in):
        print(f"[THREADS] Token not due for refresh (>{REFRESH_THRESHOLD_DAYS}d remaining). Done.")
        return 0

    print(f"[THREADS] Token expiring within {REFRESH_THRESHOLD_DAYS} days — refreshing...")
    refresh_result = refresh_threads_token(config, http, logger)
    if not refresh_result.success:
        print(f"[THREADS] Refresh FAILED: {refresh_result.status} — {refresh_result.error}")
        return 1

    # Validate new token before writing to GitHub Secrets.
    print("[THREADS] Validating refreshed token...")
    new_config = ThreadsConfig(
        user_id=config.user_id,
        access_token=refresh_result.access_token,
        app_id=config.app_id,
        app_secret=config.app_secret,
        api_version=config.api_version,
    )
    new_validation = validate_threads_token(new_config, http, logger)
    if not new_validation.valid:
        print(f"[THREADS] Refreshed token failed validation: {new_validation.status} — {new_validation.error}")
        print("[THREADS] Keeping existing GitHub Secret unchanged.")
        return 1

    print("[THREADS] Refreshed token validated. Updating GitHub Secret THREADS_ACCESS_TOKEN...")
    try:
        update_github_secret("THREADS_ACCESS_TOKEN", refresh_result.access_token)
    except Exception as exc:
        print(f"[THREADS] ERROR: Failed to update GitHub Secret: {exc}")
        return 2

    print(f"[THREADS] Done. New token expires in ~{refresh_result.expires_in}s.")
    return 0


def check_instagram(flags: FeatureFlags, http: HttpClient) -> int:
    logger = get_logger("token_health.instagram")
    config = InstagramConfig.from_env()

    print("[INSTAGRAM] Validating token...")
    result = validate_instagram_token(config, http, logger)
    if not result.valid:
        print(f"[INSTAGRAM] Token INVALID: {result.status} — {result.error}")
        return 1

    expires_in = result.expires_in
    print(f"[INSTAGRAM] Token valid (user={result.username}, expires_in={expires_in}s).")

    if not _needs_refresh(expires_in):
        print(f"[INSTAGRAM] Token not due for refresh (>{REFRESH_THRESHOLD_DAYS}d remaining). Done.")
        return 0

    print(f"[INSTAGRAM] Token expiring within {REFRESH_THRESHOLD_DAYS} days — refreshing...")
    refresh_result = refresh_instagram_token(config, http, logger)
    if not refresh_result.success:
        print(f"[INSTAGRAM] Refresh FAILED: {refresh_result.status} — {refresh_result.error}")
        return 1

    # Validate new token before writing to GitHub Secrets.
    print("[INSTAGRAM] Validating refreshed token...")
    new_config = InstagramConfig(
        user_id=config.user_id,
        access_token=refresh_result.access_token,
        api_version=config.api_version,
    )
    new_validation = validate_instagram_token(new_config, http, logger)
    if not new_validation.valid:
        print(f"[INSTAGRAM] Refreshed token failed validation: {new_validation.status} — {new_validation.error}")
        print("[INSTAGRAM] Keeping existing GitHub Secret unchanged.")
        return 1

    print("[INSTAGRAM] Refreshed token validated. Updating GitHub Secret IG_TOKEN...")
    try:
        update_github_secret("IG_TOKEN", refresh_result.access_token)
    except Exception as exc:
        print(f"[INSTAGRAM] ERROR: Failed to update GitHub Secret: {exc}")
        return 2

    print(f"[INSTAGRAM] Done. New token expires in ~{refresh_result.expires_in}s.")
    return 0


def check_facebook(flags: FeatureFlags, http: HttpClient) -> int:
    logger = get_logger("token_health.facebook")
    config = FacebookConfig.from_env()

    if not config.app_id or not config.app_secret:
        print(
            "[FACEBOOK] WARNING: FACEBOOK_APP_ID or FACEBOOK_APP_SECRET not set. "
            "Using /me fallback (no expiry data). Add these secrets for full validation."
        )

    print("[FACEBOOK] Validating token...")
    result = validate_facebook_token(config, http, logger)
    if not result.valid:
        print(f"[FACEBOOK] Token INVALID: {result.status} — {result.error}")
        return 1

    expires_in = result.expires_in
    if expires_in is None or expires_in == 0:
        print("[FACEBOOK] Token valid and non-expiring (correct for Page tokens). Done.")
    else:
        # Unexpected: a Page token that expires. Alert but don't try to refresh
        # (FB Page tokens cannot be refreshed programmatically).
        print(
            f"[FACEBOOK] WARNING: Page token expires in {expires_in}s (~{expires_in//86400}d). "
            "This usually means the token was generated from a short-lived user token. "
            "Regenerate FB_PAGE_TOKEN manually from a long-lived user token."
        )
        if expires_in < REFRESH_THRESHOLD_SECONDS:
            print("[FACEBOOK] Token expiry within threshold — manual action required.")
            return 1

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Meta token health check and auto-refresh.")
    parser.add_argument(
        "--platform",
        required=True,
        choices=["threads", "instagram", "facebook"],
        help="Which platform to check.",
    )
    args = parser.parse_args()

    flags = FeatureFlags.from_env()
    http = HttpClient.from_flags(flags, None)

    if args.platform == "threads":
        return check_threads(flags, http)
    if args.platform == "instagram":
        return check_instagram(flags, http)
    if args.platform == "facebook":
        return check_facebook(flags, http)

    print(f"Unknown platform: {args.platform}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
