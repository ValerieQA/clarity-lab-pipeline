#!/usr/bin/env python3
"""
Retry Instagram publishing for the last partial_failure topic.

Reads topics.csv, finds the most recent topic with partial_failure status
where Instagram did not publish, and republishes it using the saved
Cloudinary image URL.

Usage:
    python scripts/retry_instagram.py [--dry-run]
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from http_utils import HttpClient
from meta_tokens import validate_instagram_token
from runtime_config import FeatureFlags, InstagramConfig
from structured_logging import get_logger, log_event

import os

IG_USER_ID = os.environ["IG_USER_ID"]
IG_TOKEN   = os.environ["IG_TOKEN"]
TOPICS_FILE = Path("topics.csv")


def find_failed_instagram_topic(rows: list[dict]) -> dict | None:
    """Return the most recent topic that failed Instagram publishing."""
    candidates = [
        r for r in rows
        if r.get("Pipeline State", "") == "partial_failure"
        and r.get("Master Image URL", "").strip()
    ]
    return candidates[-1] if candidates else None


def publish_instagram(caption: str, image_url: str, flags: FeatureFlags, dry_run: bool) -> str:
    import time, requests

    logger = get_logger("retry_instagram")
    config = InstagramConfig.from_env()
    http = HttpClient.from_flags(flags, logger)

    print("[INSTAGRAM] Validating token...")
    check = validate_instagram_token(config, http, logger)
    if not check.valid:
        raise SystemExit(f"[INSTAGRAM] Token invalid: {check.error}")

    if dry_run:
        print(f"[DRY RUN] Would publish to Instagram with image: {image_url[:60]}...")
        return "dry-run-id"

    print("[INSTAGRAM] Creating container...")
    r = requests.post(
        f"https://graph.facebook.com/v19.0/{IG_USER_ID}/media",
        data={"image_url": image_url, "caption": caption, "access_token": IG_TOKEN},
    )
    data = r.json()
    if "error" in data:
        raise SystemExit(f"[INSTAGRAM] Container error: {data['error']['message']}")

    container_id = data["id"]
    print(f"[INSTAGRAM] Container: {container_id}, waiting 5s...")
    time.sleep(5)

    print("[INSTAGRAM] Publishing...")
    r2 = requests.post(
        f"https://graph.facebook.com/v19.0/{IG_USER_ID}/media_publish",
        data={"creation_id": container_id, "access_token": IG_TOKEN},
    )
    result = r2.json()
    if "error" in result:
        raise SystemExit(f"[INSTAGRAM] Publish error: {result['error']['message']}")

    post_id = result["id"]
    print(f"[INSTAGRAM] Published: {post_id}")
    return post_id


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    rows = []
    with open(TOPICS_FILE, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    topic = find_failed_instagram_topic(rows)
    if not topic:
        print("No partial_failure topics with a saved image URL found. Nothing to retry.")
        return

    print(f"[RETRY] Topic: {topic['Topic / Working Title']}")
    print(f"[RETRY] Image: {topic['Master Image URL'][:60]}...")

    hashtags = "#clarity #reflection #selfawareness #InnerOS #mindfulness #humandesign #AI"
    caption  = f"{topic.get('Instagram Article Draft', topic['Topic / Working Title'])}\n\n{hashtags}"

    flags = FeatureFlags.from_env()
    post_id = publish_instagram(caption, topic["Master Image URL"], flags, args.dry_run)

    if not args.dry_run:
        # Update topics.csv — mark Instagram as published
        idx = rows.index(topic)
        rows[idx]["Pipeline State"] = "completed"
        rows[idx]["Workflow Status"] = "Complete"
        rows[idx]["Status"]          = "Published"
        rows[idx]["Publish Status Code"] = "200"

        with open(TOPICS_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        print(f"[RETRY] topics.csv updated — topic marked as completed.")

    print(f"\n✅ Instagram retry done! Post ID: {post_id}")


if __name__ == "__main__":
    main()
