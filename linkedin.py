"""
Clarity Lab — LinkedIn draft-and-publish workflow.

Generates a LinkedIn post in Valerie's own voice (English + Russian working
translation), stores it in data/linkedin_posts.csv, and publishes the English
version to her personal profile when publishing is enabled.

Safety model matches the rest of the pipeline:
  ENABLE_LINKEDIN_PUBLISHING=false   -> generate and store only
  LINKEDIN_REQUIRE_APPROVAL=true     -> never auto-publishes, emails the draft
  DRY_RUN=true                       -> no network writes at all

Run:
    python linkedin.py                 # generate a draft
    python linkedin.py --publish-due   # publish approved drafts
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from openai import OpenAI

from http_utils import HttpClient
from prompt_loader import LINKEDIN_PROMPT_PATH, load_prompt
from runtime_config import FeatureFlags, LinkedInConfig
from structured_logging import get_logger, log_event

LOGGER = get_logger("linkedin")
FLAGS = FeatureFlags.from_env()
LI = LinkedInConfig.from_env()
HTTP = HttpClient.from_flags(FLAGS, LOGGER)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
TOPICS_FILE = Path(os.environ.get("TOPICS_FILE", "topics.csv"))
LINKEDIN_DB = Path("data/linkedin_posts.csv")

LINKEDIN_FIELDS = [
    "post_id",
    "created_at",
    "source_topic",
    "case_used",
    "text_en",
    "text_ru",
    "status",
    "published_at",
    "external_post_id",
    "http_status",
    "verified",
    "error_message",
    "notes",
]

API_BASE = "https://api.linkedin.com"
USERINFO_URL = f"{API_BASE}/v2/userinfo"
POSTS_URL = f"{API_BASE}/rest/posts"

# How many recent posts to show the model so it does not repeat a case.
RECENT_WINDOW = 8
# The same case may not be reused inside this many posts (~6 weeks at 2/week).
CASE_COOLDOWN = 12


# ----------------------------------------------------------------------------
# Storage
# ----------------------------------------------------------------------------

def _read_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_posts() -> list[dict]:
    return _read_rows(LINKEDIN_DB)


def append_post(row: dict) -> None:
    LINKEDIN_DB.parent.mkdir(parents=True, exist_ok=True)
    write_header = not LINKEDIN_DB.exists()
    with LINKEDIN_DB.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LINKEDIN_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in LINKEDIN_FIELDS})


def rewrite_posts(rows: list[dict]) -> None:
    LINKEDIN_DB.parent.mkdir(parents=True, exist_ok=True)
    with LINKEDIN_DB.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LINKEDIN_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in LINKEDIN_FIELDS})


def recent_cases(rows: list[dict], window: int = CASE_COOLDOWN) -> list[str]:
    return [r.get("case_used", "").strip() for r in rows[-window:] if r.get("case_used", "").strip()]


def recent_summaries(rows: list[dict], window: int = RECENT_WINDOW) -> str:
    if not rows:
        return "none yet"
    parts = []
    for r in rows[-window:]:
        text = (r.get("text_en") or "").strip().replace("\n", " ")
        parts.append(f"- [{r.get('case_used', '?')}] {text[:160]}")
    return "\n".join(parts)


# ----------------------------------------------------------------------------
# Generation
# ----------------------------------------------------------------------------

def _next_topic() -> dict:
    rows = _read_rows(TOPICS_FILE)
    for row in rows:
        if row.get("Status", "").strip().lower() in {"ready", "published"}:
            return row
    raise RuntimeError("No usable topic found in topics.csv")


def parse_sections(raw: str) -> tuple[str, str, str]:
    """Return (english, russian, case_used)."""
    def grab(tag: str) -> str:
        m = re.search(rf"==={tag}===\s*(.*?)(?====|\Z)", raw or "", re.DOTALL)
        return m.group(1).strip() if m else ""

    en = grab("LINKEDIN_EN")
    ru = grab("LINKEDIN_RU")
    case = grab("CASE") or "unspecified"

    if not en:
        raise ValueError("LinkedIn output is missing the ===LINKEDIN_EN=== section")
    if len(en) > 3000:
        raise ValueError(f"LinkedIn post is too long: {len(en)} characters")
    return en, ru, case


def generate_post(topic: dict, history: list[dict]) -> tuple[str, str, str]:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is required to generate LinkedIn content")

    client = OpenAI(
        api_key=OPENAI_API_KEY,
        max_retries=FLAGS.http_max_retries,
        timeout=FLAGS.http_timeout_seconds,
    )

    prompt = load_prompt(LINKEDIN_PROMPT_PATH).format(
        title=topic.get("Topic / Working Title", ""),
        core_observation=topic.get("Core Observation", ""),
        recent_posts=recent_summaries(history),
    )

    blocked = recent_cases(history)
    prompt += (
        f"\n\nCases used recently — do not reuse any of these: "
        f"{', '.join(blocked) if blocked else 'none'}."
        f"\n\nAfter the two sections, add a third section:\n"
        f"===CASE===\nthe short label of the case you used, e.g. crypto-keps, "
        f"vit-turnover, selerant-kyiv, ukrainian-sisters, freelancers, sdl-kyiv\n"
    )

    log_event(LOGGER, "linkedin_generation_started", platform="openai", status="running")
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1200,
        temperature=0.85,
    )
    raw = response.choices[0].message.content or ""
    return parse_sections(raw)


# ----------------------------------------------------------------------------
# Publishing
# ----------------------------------------------------------------------------

def _headers() -> dict:
    return {
        "Authorization": f"Bearer {LI.access_token}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
        "LinkedIn-Version": LI.api_version,
    }


def resolve_person_urn() -> str:
    """Person URN, from config if set, otherwise from the OpenID userinfo endpoint."""
    if LI.person_urn:
        return LI.person_urn

    resp = HTTP.get(USERINFO_URL, headers={"Authorization": f"Bearer {LI.access_token}"})
    data = resp.json()
    sub = data.get("sub")
    if not sub:
        raise RuntimeError(f"Could not resolve person URN from userinfo: {data}")
    return f"urn:li:person:{sub}"


class PublishResult:
    """Explicit outcome of a publish attempt — status code included, always."""

    def __init__(self, ok: bool, status_code: int, post_id: str = "", error: str = ""):
        self.ok = ok
        self.status_code = status_code
        self.post_id = post_id
        self.error = error

    def __str__(self) -> str:
        return f"{self.status_code} {'ok' if self.ok else 'failed'} {self.post_id or self.error}"


def publish(text: str) -> PublishResult:
    """Publish text to the personal profile.

    Never raises on an HTTP error. The status code is always returned and
    recorded, so a 401, 403, 422 or 429 is visible in the CSV and in the email
    rather than disappearing into a stack trace.
    """
    if not LI.access_token:
        return PublishResult(False, 0, error="LINKEDIN_ACCESS_TOKEN is not set")

    try:
        author = resolve_person_urn()
    except Exception as exc:
        return PublishResult(False, 0, error=f"could not resolve person URN: {exc}")

    payload = {
        "author": author,
        "commentary": text,
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }

    try:
        resp = HTTP.post(POSTS_URL, headers=_headers(), json=payload)
    except Exception as exc:
        log_event(LOGGER, "linkedin_publish_network_error", logging.ERROR,
                  platform="linkedin", status="failed", error=str(exc))
        return PublishResult(False, 0, error=f"network error: {exc}")

    code = getattr(resp, "status_code", 0)

    # LinkedIn returns 201 Created on success. Anything else is a failure,
    # and the body carries the reason.
    if code not in (200, 201):
        body = ""
        try:
            body = resp.text[:500]
        except Exception:
            pass
        reason = {
            400: "malformed request — check the payload",
            401: "token expired or invalid — re-run SETUP.md step 2",
            403: "missing w_member_social permission on the app",
            404: "endpoint or person URN not found",
            422: "LinkedIn rejected the content (duplicate or policy)",
            429: "rate limit reached — retry later",
        }.get(code, "unexpected response")
        error = f"HTTP {code}: {reason}. {body}"
        log_event(LOGGER, "linkedin_publish_rejected", logging.ERROR,
                  platform="linkedin", status="failed",
                  details={"http_status": code}, error=error)
        return PublishResult(False, code, error=error)

    # /rest/posts returns the new id in a header; some versions echo it in the body.
    post_id = ""
    try:
        post_id = resp.headers.get("x-restli-id", "") or ""
    except Exception:
        pass
    if not post_id:
        try:
            post_id = resp.json().get("id", "") or ""
        except Exception:
            post_id = ""

    if not post_id:
        # Accepted but unidentifiable. Treat as failure — we cannot verify it later.
        error = f"HTTP {code} but no post id returned; cannot verify publication"
        log_event(LOGGER, "linkedin_publish_unverifiable", logging.ERROR,
                  platform="linkedin", status="failed",
                  details={"http_status": code}, error=error)
        return PublishResult(False, code, error=error)

    log_event(LOGGER, "linkedin_published", platform="linkedin", status="published",
              details={"http_status": code, "post_id": post_id})
    return PublishResult(True, code, post_id=post_id)


def verify_published(post_id: str) -> bool:
    """Read the post back. Confirms it actually exists on the profile."""
    if not post_id:
        return False
    from urllib.parse import quote
    url = f"{POSTS_URL}/{quote(post_id, safe='')}"
    try:
        resp = HTTP.get(url, headers=_headers())
    except Exception as exc:
        log_event(LOGGER, "linkedin_verify_error", logging.WARNING,
                  platform="linkedin", status="unknown", error=str(exc))
        return False
    code = getattr(resp, "status_code", 0)
    log_event(LOGGER, "linkedin_verified", platform="linkedin",
              status="ok" if code == 200 else "missing",
              details={"http_status": code, "post_id": post_id})
    return code == 200


# ----------------------------------------------------------------------------
# Commands
# ----------------------------------------------------------------------------

def _email(subject_body: str) -> None:
    try:
        from notifications.email_reporter import send_email
        send_email("Clarity Lab — LinkedIn draft ready", subject_body)
    except Exception as exc:  # email must never break the run
        log_event(LOGGER, "linkedin_email_failed", logging.WARNING,
                  platform="email", status="failed", error=str(exc))


def create_draft() -> dict:
    history = load_posts()
    topic = _next_topic()
    text_en, text_ru, case = generate_post(topic, history)

    row = {
        "post_id": f"li_{uuid.uuid4().hex[:12]}",
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "source_topic": topic.get("Topic / Working Title", ""),
        "case_used": case,
        "text_en": text_en,
        "text_ru": text_ru,
        "status": "draft",
        "published_at": "",
        "external_post_id": "",
        "http_status": "",
        "verified": "",
        "error_message": "",
        "notes": "",
    }

    publish_allowed = (
        LI.enable_publishing
        and not LI.require_approval
        and not FLAGS.dry_run
    )

    if publish_allowed:
        result = publish(text_en)
        row["http_status"] = str(result.status_code)
        if result.ok:
            row["external_post_id"] = result.post_id
            row["status"] = "published"
            row["published_at"] = datetime.now(tz=timezone.utc).isoformat()
            row["verified"] = "yes" if verify_published(result.post_id) else "unconfirmed"
        else:
            row["status"] = "failed"
            row["error_message"] = result.error
    else:
        reason = (
            "dry run" if FLAGS.dry_run
            else "publishing disabled" if not LI.enable_publishing
            else "approval required"
        )
        row["notes"] = f"not published: {reason}"

    append_post(row)

    _email(
        f"Status: {row['status']}  |  HTTP {row['http_status'] or 'n/a'}  |  "
        f"verified: {row['verified'] or 'n/a'}\n"
        f"{row['error_message'] or row['notes'] or ''}\n"
        f"Topic: {row['source_topic']}\n"
        f"Case: {case}\n\n"
        f"--- ENGLISH ---\n{text_en}\n\n"
        f"--- RUSSIAN (working translation) ---\n{text_ru}\n"
    )

    print(f"[LINKEDIN] {row['status']} — {row['post_id']}")
    return row


def publish_due() -> int:
    """Publish every row marked 'approved'. Used when approval is required."""
    rows = load_posts()
    published = 0
    for row in rows:
        if row.get("status") != "approved":
            continue
        if FLAGS.dry_run or not LI.enable_publishing:
            print(f"[LINKEDIN] would publish {row['post_id']} (dry run / disabled)")
            continue
        result = publish(row["text_en"])
        row["http_status"] = str(result.status_code)
        if result.ok:
            row["external_post_id"] = result.post_id
            row["status"] = "published"
            row["published_at"] = datetime.now(tz=timezone.utc).isoformat()
            row["verified"] = "yes" if verify_published(result.post_id) else "unconfirmed"
            published += 1
        else:
            row["status"] = "failed"
            row["error_message"] = result.error
    rewrite_posts(rows)
    print(f"[LINKEDIN] published {published}")
    return published


def main() -> int:
    parser = argparse.ArgumentParser(description="Clarity Lab LinkedIn workflow")
    parser.add_argument("--publish-due", action="store_true",
                        help="publish rows already marked approved")
    args = parser.parse_args()

    try:
        if args.publish_due:
            publish_due()
        else:
            create_draft()
    except Exception as exc:
        log_event(LOGGER, "linkedin_run_failed", logging.ERROR,
                  platform="linkedin", status="failed", error=str(exc))
        print(f"[LINKEDIN] failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
