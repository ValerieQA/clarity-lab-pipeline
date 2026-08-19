"""
LinkedIn access token health check.

LinkedIn does not issue refresh tokens outside the partner programme, so the
access token expires roughly every 60 days and then fails silently. This script
verifies the token and warns by email before it dies.

Designed to be added to the existing weekly token_check.yml workflow, next to
the Meta token checks.

Exit codes:
    0 — token valid
    1 — token invalid, expired, or missing
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests

from runtime_config import LinkedInConfig
from structured_logging import get_logger, log_event

LOGGER = get_logger("linkedin_token_check")
LI = LinkedInConfig.from_env()

USERINFO_URL = "https://api.linkedin.com/v2/userinfo"
INTROSPECT_URL = "https://www.linkedin.com/oauth/v2/introspectToken"

WARN_DAYS = 10


def _introspect() -> dict | None:
    """Ask LinkedIn when the token expires. Needs client id and secret."""
    if not (LI.client_id and LI.client_secret):
        return None
    try:
        resp = requests.post(
            INTROSPECT_URL,
            data={
                "client_id": LI.client_id,
                "client_secret": LI.client_secret,
                "token": LI.access_token,
            },
            timeout=15,
        )
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception:
        return None


def _notify(subject_body: str) -> None:
    try:
        from notifications.email_reporter import send_token_alert
        send_token_alert(subject_body)
    except Exception as exc:
        print(f"[LINKEDIN] could not send email: {exc}", file=sys.stderr)


def main() -> int:
    if not LI.access_token:
        msg = "LINKEDIN_ACCESS_TOKEN is not set. LinkedIn publishing is not configured."
        print(f"[LINKEDIN] {msg}")
        log_event(LOGGER, "linkedin_token_missing", platform="linkedin", status="missing")
        _notify(msg)
        return 1

    # 1. Does the token actually work?
    try:
        resp = requests.get(
            USERINFO_URL,
            headers={"Authorization": f"Bearer {LI.access_token}"},
            timeout=15,
        )
    except Exception as exc:
        print(f"[LINKEDIN] network error: {exc}", file=sys.stderr)
        return 1

    if resp.status_code == 401:
        msg = (
            "LinkedIn access token has expired.\n\n"
            "LinkedIn issues no refresh token outside the partner programme, so this "
            "has to be redone by hand — it takes about three minutes.\n\n"
            "Steps are in the LinkedIn SETUP.md, section 'Шаг 2'. After getting the new "
            "token, replace the LINKEDIN_ACCESS_TOKEN secret in GitHub.\n\n"
            "Until then LinkedIn posts will not publish. Everything else keeps running."
        )
        print("[LINKEDIN] token expired")
        log_event(LOGGER, "linkedin_token_expired", platform="linkedin", status="expired")
        _notify(msg)
        return 1

    if resp.status_code != 200:
        msg = f"LinkedIn token check returned {resp.status_code}: {resp.text[:300]}"
        print(f"[LINKEDIN] {msg}", file=sys.stderr)
        log_event(LOGGER, "linkedin_token_unexpected", platform="linkedin",
                  status="failed", error=msg)
        _notify(msg)
        return 1

    who = resp.json().get("name", "unknown")
    print(f"[LINKEDIN] token valid — {who}")

    # 2. How long has it got left?
    info = _introspect()
    if info and info.get("expires_at"):
        expires = datetime.fromtimestamp(int(info["expires_at"]), tz=timezone.utc)
        days_left = (expires - datetime.now(tz=timezone.utc)).days
        print(f"[LINKEDIN] expires {expires.date()} ({days_left} days left)")

        if days_left <= WARN_DAYS:
            _notify(
                f"LinkedIn access token expires in {days_left} days "
                f"(on {expires.date()}).\n\n"
                "It cannot refresh itself. Re-run the steps in LinkedIn SETUP.md, "
                "section 'Шаг 2', and replace the LINKEDIN_ACCESS_TOKEN secret.\n\n"
                "Takes about three minutes. If it lapses, LinkedIn posts stop "
                "publishing silently."
            )
            log_event(LOGGER, "linkedin_token_expiring", platform="linkedin",
                      status="warning", details={"days_left": days_left})
    else:
        print("[LINKEDIN] expiry unknown — set LINKEDIN_CLIENT_ID and "
              "LINKEDIN_CLIENT_SECRET to enable the early warning")

    log_event(LOGGER, "linkedin_token_valid", platform="linkedin", status="ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
