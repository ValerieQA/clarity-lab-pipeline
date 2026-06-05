#!/usr/bin/env python3
"""
Retry publishing for a single failed channel.

Reads the last topic with <channel>_status = failed from topics.csv.
Uses saved master_image_url, ig_caption, fb_message — does NOT call GPT,
does NOT regenerate images.

Usage:
    python scripts/retry_channel.py --channel instagram
    python scripts/retry_channel.py --channel facebook
    python scripts/retry_channel.py --channel threads
    python scripts/retry_channel.py --channel instagram --dry-run
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from http_utils import HttpClient
from meta_tokens import validate_facebook_token, validate_instagram_token
from publication_state import write_topics
from runtime_config import FacebookConfig, FeatureFlags, InstagramConfig
from structured_logging import get_logger

TOPICS_FILE = Path("topics.csv")
REQUIRED_CHANNELS = {"instagram", "facebook", "wix"}


# ──────────────────────────────────────────────
# CSV helpers
# ──────────────────────────────────────────────

def load_topics() -> tuple[list[dict], list[str]]:
    with open(TOPICS_FILE, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    return rows, fieldnames


def find_failed_topic(rows: list[dict], channel: str) -> dict | None:
    col = f"{channel.capitalize()} Status"
    # Primary: explicit failed status.
    candidates = [r for r in rows if r.get(col, "").strip().lower() == "failed"]
    if candidates:
        return candidates[-1]
    # Fallback: partial_failure pipeline with no channel status set yet + image saved.
    candidates = [
        r for r in rows
        if r.get("Pipeline State", "").strip() in ("partial_failure", "")
        and r.get("Workflow Status", "").strip().lower() in ("partial_failure", "")
        and r.get("Status", "").strip().lower() in ("partial failure", "partial_failure")
        and r.get("Master Image URL", "").strip()
        and r.get(col, "").strip() == ""
    ]
    return candidates[-1] if candidates else None


def resolve_ig_caption(topic: dict) -> str:
    """Return saved IG Caption or reconstruct from Instagram Article Draft."""
    caption = topic.get("IG Caption", "").strip()
    if caption:
        return caption
    draft = topic.get("Instagram Article Draft", "").strip()
    if draft:
        hashtags = "#clarity #reflection #selfawareness #InnerOS #mindfulness #humandesign #AI"
        return f"{draft}\n\n{hashtags}"
    return topic.get("Topic / Working Title", "").strip()


def resolve_fb_message(topic: dict) -> str:
    """Return saved FB Message or reconstruct from Instagram Article Draft + URL."""
    msg = topic.get("FB Message", "").strip()
    if msg:
        return msg
    draft = topic.get("Instagram Article Draft", topic.get("Topic / Working Title", "")).strip()
    post_url = topic.get("Website Published URL", "").strip()
    return f"{draft[:500]}\n\n{post_url}".strip()


def update_topic_status(rows: list[dict], topic: dict, channel: str, status: str, error: str = "") -> None:
    col = f"{channel.capitalize()} Status"
    idx = rows.index(topic)
    rows[idx][col] = status

    # Recompute Pipeline State.
    required_statuses = [
        rows[idx].get(f"{c.capitalize()} Status", "skipped")
        for c in REQUIRED_CHANNELS
    ]
    if all(s in ("published", "skipped") for s in required_statuses):
        rows[idx]["Pipeline State"] = "completed"
        rows[idx]["Status"] = "Published"
        rows[idx]["Workflow Status"] = "Complete"
    elif any(s == "failed" for s in required_statuses):
        rows[idx]["Pipeline State"] = "partial_failure"
        rows[idx]["Status"] = "Partial Failure"

    if error:
        existing = rows[idx].get("Publication Errors", "")
        rows[idx]["Publication Errors"] = f"{existing} | {channel}: {error[:200]}".strip(" |")

    write_topics(str(TOPICS_FILE), rows)


# ──────────────────────────────────────────────
# Channel publishers
# ──────────────────────────────────────────────

def retry_instagram(topic: dict, flags: FeatureFlags, dry_run: bool) -> str:
    image_url = topic.get("Master Image URL", "").strip()
    caption   = resolve_ig_caption(topic)
    if not image_url:
        raise ValueError("Master Image URL is empty — cannot retry without saved image.")
    if not caption:
        raise ValueError("IG Caption is empty — cannot retry without saved caption.")

    logger  = get_logger("retry.instagram")
    config  = InstagramConfig.from_env()
    http    = HttpClient.from_flags(flags, logger)

    print("[INSTAGRAM] Validating token...")
    check = validate_instagram_token(config, http, logger)
    if not check.valid:
        raise RuntimeError(f"Token invalid: {check.error}")

    if dry_run:
        print(f"[DRY RUN] Would publish to Instagram — image: {image_url[:60]}")
        return "dry-run-id"

    ig_user_id = os.environ["IG_USER_ID"]
    ig_token   = os.environ["IG_TOKEN"]

    import requests
    print("[INSTAGRAM] Creating container...")
    r = requests.post(
        f"https://graph.facebook.com/v19.0/{ig_user_id}/media",
        data={"image_url": image_url, "caption": caption, "access_token": ig_token},
        timeout=30,
    )
    data = r.json()
    if "error" in data:
        raise RuntimeError(f"Container error: {data['error']['message']}")

    container_id = data["id"]
    print(f"[INSTAGRAM] Container: {container_id}, waiting 5s...")
    time.sleep(5)

    r2 = requests.post(
        f"https://graph.facebook.com/v19.0/{ig_user_id}/media_publish",
        data={"creation_id": container_id, "access_token": ig_token},
        timeout=30,
    )
    result = r2.json()
    if "error" in result:
        raise RuntimeError(f"Publish error: {result['error']['message']}")

    post_id = result["id"]
    print(f"[INSTAGRAM] Published: {post_id}")
    return post_id


def retry_facebook(topic: dict, flags: FeatureFlags, dry_run: bool) -> str:
    image_url  = topic.get("Master Image URL", "").strip()
    fb_message = resolve_fb_message(topic)
    if not image_url:
        raise ValueError("Master Image URL is empty — cannot retry without saved image.")
    if not fb_message:
        raise ValueError("FB Message is empty — cannot retry without saved message.")

    logger = get_logger("retry.facebook")
    config = FacebookConfig.from_env()
    http   = HttpClient.from_flags(flags, logger)

    print("[FACEBOOK] Validating token...")
    check = validate_facebook_token(config, http, logger)
    if not check.valid:
        raise RuntimeError(f"Token invalid: {check.error}")

    if dry_run:
        print(f"[DRY RUN] Would publish to Facebook — image: {image_url[:60]}")
        return "dry-run-id"

    import requests
    fb_page_id    = os.environ["FB_PAGE_ID"]
    fb_page_token = os.environ["FB_PAGE_TOKEN"]

    print("[FACEBOOK] Publishing...")
    r = requests.post(
        f"https://graph.facebook.com/v19.0/{fb_page_id}/photos",
        data={"url": image_url, "caption": fb_message, "access_token": fb_page_token},
        timeout=30,
    )
    result = r.json()
    if "error" in result:
        raise RuntimeError(f"Publish error: {result['error']['message']}")

    post_id = result.get("post_id") or result.get("id", "")
    print(f"[FACEBOOK] Published: {post_id}")
    return post_id


def retry_threads(topic: dict, flags: FeatureFlags, dry_run: bool) -> str:
    from meta_tokens import validate_threads_token
    from runtime_config import ThreadsConfig

    logger = get_logger("retry.threads")
    config = ThreadsConfig.from_env()
    http   = HttpClient.from_flags(flags, logger)

    print("[THREADS] Validating token...")
    check = validate_threads_token(config, http, logger)
    if not check.valid:
        raise RuntimeError(f"Token invalid: {check.error}")

    # Threads retry: regenerate is required since text isn't saved in pipeline.
    # Use topic title + observation as fallback text.
    text = topic.get("Topic / Working Title", "").strip()
    if not text:
        raise ValueError("No topic title found for Threads retry.")

    if dry_run:
        print(f"[DRY RUN] Would publish to Threads — text: {text[:60]}")
        return "dry-run-id"

    import requests
    threads_user_id = os.environ["THREADS_USER_ID"]
    threads_token   = os.environ.get("THREADS_ACCESS_TOKEN") or os.environ.get("THREADS_TOKEN", "")

    print("[THREADS] Creating container...")
    r = requests.post(
        f"https://graph.threads.net/v1.0/{threads_user_id}/threads",
        data={"text": text[:320], "media_type": "TEXT", "access_token": threads_token},
        timeout=30,
    )
    data = r.json()
    if "error" in data:
        raise RuntimeError(f"Container error: {data['error']['message']}")

    container_id = data["id"]
    time.sleep(3)

    r2 = requests.post(
        f"https://graph.threads.net/v1.0/{threads_user_id}/threads_publish",
        data={"creation_id": container_id, "access_token": threads_token},
        timeout=30,
    )
    result = r2.json()
    if "error" in result:
        raise RuntimeError(f"Publish error: {result['error']['message']}")

    post_id = result["id"]
    print(f"[THREADS] Published: {post_id}")
    return post_id


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

PUBLISHERS = {
    "instagram": retry_instagram,
    "facebook":  retry_facebook,
    "threads":   retry_threads,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Retry a single failed publishing channel.")
    parser.add_argument("--channel", required=True, choices=list(PUBLISHERS), help="Channel to retry")
    parser.add_argument("--dry-run", action="store_true", help="Validate only, do not publish")
    args = parser.parse_args()

    rows, _ = load_topics()
    topic = find_failed_topic(rows, args.channel)

    if not topic:
        print(f"No topic with {args.channel}_status = failed found in topics.csv.")
        sys.exit(0)

    print(f"[RETRY] Channel:  {args.channel}")
    print(f"[RETRY] Topic:    {topic['Topic / Working Title']}")
    print(f"[RETRY] Image:    {topic.get('Master Image URL', '')[:60]}")

    flags = FeatureFlags.from_env()
    try:
        PUBLISHERS[args.channel](topic, flags, args.dry_run)
        if not args.dry_run:
            update_topic_status(rows, topic, args.channel, "published")
            print(f"[RETRY] topics.csv updated — {args.channel} → published")
        print(f"\n✅ Retry successful: {args.channel}")
    except Exception as exc:
        if not args.dry_run:
            update_topic_status(rows, topic, args.channel, "failed", error=str(exc))
        print(f"\n❌ Retry failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
