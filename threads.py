"""
Clarity Lab — Threads Pipeline
Production-safe draft-first Threads workflow.
"""

from __future__ import annotations

import argparse
import csv
import logging
import re
import time
from datetime import datetime, timezone

from openai import OpenAI

from content_validation import ContentValidationError, parse_thread_series as parse_series_sections, validate_threads_posts
from http_utils import HttpClient
from meta_tokens import validate_threads_token
from prompt_loader import THREADS_PROMPT_PATH, load_prompt
from runtime_config import FeatureFlags, ThreadsConfig
from structured_logging import get_logger, log_event
from threads_store import append_post, draft_record, find_duplicate, published_thread_count_on, update_post
from threads_learning import collect_threads_comments, generate_weekly_report

# ============================================================
# CONFIG
# ============================================================

import os

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
TOPICS_FILE = "topics.csv"
CONTENT_TYPES = ["spark", "question", "thread_series"]
FLAGS = FeatureFlags.from_env()
THREADS_CONFIG = ThreadsConfig.from_env()
LOGGER = get_logger("threads")
HTTP = HttpClient.from_flags(FLAGS, LOGGER)

# ============================================================
# HELPERS
# ============================================================


def clean_markdown(text):
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\*{1,3}(.*?)\*{1,3}', r'\1', text)
    text = re.sub(r'^[-*_]{3,}$', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def truncate_to_limit(text, limit=320):
    if len(text) <= limit:
        return text
    return text[:limit - 3].rsplit(' ', 1)[0] + "..."


# ============================================================
# STEP 1: Get topic
# ============================================================


def get_topic_for_threads():
    rows = []
    with open(TOPICS_FILE, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    published = [r for r in rows if r.get("Status", "").strip().lower() == "published"]

    if not published:
        ready = [r for r in rows if r.get("Status", "").strip().lower() in ("ready", "")]
        if not ready:
            raise Exception("No topics available in topics.csv")
        topic = ready[0]
        index = rows.index(topic)
    else:
        topic = published[-1]
        index = rows.index(topic)

    print(f"[THREADS] Topic: {topic['Topic / Working Title']}")
    return index, topic


def get_content_type(index):
    return CONTENT_TYPES[index % len(CONTENT_TYPES)]


# ============================================================
# STEP 2: Generate Threads content via GPT
# ============================================================


def generate_threads_content(topic_row, content_type):
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is required to generate Threads content")
    client = OpenAI(api_key=OPENAI_API_KEY, max_retries=FLAGS.http_max_retries, timeout=FLAGS.http_timeout_seconds)
    base_prompt = load_prompt(THREADS_PROMPT_PATH)
    prompt = f"""
{base_prompt}

---

Content type: {content_type}
Topic: {topic_row['Topic / Working Title']}
Core observation: {topic_row['Core Observation']}
Audience question: {topic_row['Audience Question']}

Hard character limit: 300 characters total. The post must be complete and self-contained within 300 characters. Do not exceed this.
"""

    print(f"[GPT] Generating Threads content (type: {content_type})...")
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=120,
        temperature=0.8,
    )

    text = response.choices[0].message.content.strip()
    word_count = len(text.split())
    print(f"[GPT] Threads content generated ({word_count} words)")
    return text


def _validate_word_count(text: str) -> str:
    """Trim to max words if GPT exceeded the limit. Returns cleaned text."""
    words = text.split()
    if len(words) <= FLAGS.threads_max_words:
        return text
    trimmed = " ".join(words[:FLAGS.threads_max_words])
    # Try to end on a complete sentence.
    for punct in (".", "!", "?"):
        last = trimmed.rfind(punct)
        if last > len(trimmed) * 0.6:
            trimmed = trimmed[:last + 1]
            break
    print(f"[THREADS] Post trimmed to {len(trimmed.split())} words (was {len(words)})")
    return trimmed


def posts_from_raw(raw_content: str, content_type: str) -> list[str]:
    if content_type == "thread_series":
        posts = parse_series_sections(raw_content)
    else:
        cleaned = clean_markdown(raw_content)
        validated = _validate_word_count(cleaned)
        posts = [truncate_to_limit(validated)]
    validate_threads_posts(posts)
    return posts


# ============================================================
# STEP 3: Publish to Threads (disabled by default)
# ============================================================


def create_threads_container(text, reply_to_id=None):
    params = {
        "text": truncate_to_limit(clean_markdown(text)),
        "media_type": "TEXT",
        "access_token": THREADS_CONFIG.access_token,
    }
    if reply_to_id:
        params["reply_to_id"] = reply_to_id

    response = HTTP.post(
        f"https://graph.threads.net/{THREADS_CONFIG.api_version}/{THREADS_CONFIG.user_id}/threads",
        platform="threads",
        data=params,
    )
    result = response.json()

    if "error" in result:
        raise Exception(f"[THREADS] Container error: {result['error']['message']}")
    if "id" not in result:
        raise Exception(f"[THREADS] Unexpected response: {result}")

    return result["id"]


def publish_threads_container(container_id):
    response = HTTP.post(
        f"https://graph.threads.net/{THREADS_CONFIG.api_version}/{THREADS_CONFIG.user_id}/threads_publish",
        platform="threads",
        data={"creation_id": container_id, "access_token": THREADS_CONFIG.access_token},
    )
    result = response.json()

    if "error" in result:
        raise Exception(f"[THREADS] Publish error: {result['error']['message']}")
    if "id" not in result:
        raise Exception(f"[THREADS] Unexpected publish response: {result}")

    return result["id"]


def publish_single_post(text):
    container_id = create_threads_container(text)
    time.sleep(3)
    post_id = publish_threads_container(container_id)
    print(f"[THREADS] Post published: {post_id}")
    return post_id


def can_publish_automatically(flags: FeatureFlags) -> bool:
    return flags.enable_threads_publishing and not flags.threads_require_approval and not flags.dry_run


def remaining_daily_threads_quota(flags: FeatureFlags) -> int:
    return max(0, flags.threads_daily_post_limit - published_thread_count_on())


def publication_block_reason(flags: FeatureFlags, posts: list[str]) -> str:
    if flags.dry_run:
        return "dry_run_enabled"
    if not flags.enable_threads_publishing:
        return "publishing_disabled"
    if flags.threads_require_approval:
        return "approval_required"
    if len(posts) > flags.threads_posts_per_run:
        return "posts_per_run_limit_exceeded"
    if len(posts) > remaining_daily_threads_quota(flags):
        return "daily_post_limit_exceeded"
    return ""


def publish_thread_series(posts):
    print(f"[THREADS] Publishing thread series ({len(posts)} posts)...")
    post_ids = []
    reply_to_id = None

    for i, post_text in enumerate(posts):
        print(f"[THREADS] Publishing post {i + 1}/{len(posts)}...")
        container_id = create_threads_container(post_text, reply_to_id=reply_to_id)
        time.sleep(3)
        post_id = publish_threads_container(container_id)
        post_ids.append(post_id)
        reply_to_id = post_id
        time.sleep(5)

    print(f"[THREADS] Thread series published: {len(post_ids)} posts")
    return post_ids


# ============================================================
# MAIN
# ============================================================


def run_threads_pipeline():
    print(f"\n{'=' * 60}")
    print(f"Clarity Lab Threads Pipeline — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'=' * 60}\n")
    log_event(LOGGER, "threads_pipeline_started", status="dry_run" if FLAGS.dry_run else "running", details=FLAGS.__dict__)

    index, topic = get_topic_for_threads()
    content_type = get_content_type(index)
    print(f"[THREADS] Content type: {content_type}")

    raw_content = generate_threads_content(topic, content_type)
    posts = posts_from_raw(raw_content, content_type)
    generated_text = "\n\n".join(posts)

    duplicate = find_duplicate(generated_text, extra_texts=[topic.get("Instagram Article Draft", "")])
    source_topic = topic["Topic / Working Title"]
    if duplicate.is_duplicate:
        log_event(
            LOGGER,
            "threads_duplicate_detected",
            logging.WARNING,
            platform="threads",
            status="rejected",
            details={"similarity": duplicate.similarity, "matched_post_id": duplicate.matched_post_id},
        )
        record = draft_record(source_topic, generated_text, content_type, content_type, status="rejected", error_message="duplicate_detected")
        append_post(record)
        print(f"[THREADS] Duplicate detected ({duplicate.similarity:.2f}); draft rejected and not published")
        return

    record = draft_record(source_topic, generated_text, content_type, content_type, status="draft")
    append_post(record)
    print(f"[THREADS] Draft saved: {record['post_id']}")

    block_reason = publication_block_reason(FLAGS, posts)
    if block_reason:
        log_event(
            LOGGER,
            "threads_publish_skipped",
            platform="threads",
            status="skipped",
            details={
                "reason": block_reason,
                "dry_run": FLAGS.dry_run,
                "enabled": FLAGS.enable_threads_publishing,
                "approval_required": FLAGS.threads_require_approval,
                "posts_in_candidate": len(posts),
                "posts_per_run": FLAGS.threads_posts_per_run,
                "remaining_daily_quota": remaining_daily_threads_quota(FLAGS),
                "post_id": record["post_id"],
            },
        )
        print(f"[THREADS] Publishing skipped safely: {block_reason}")
        return

    token_result = validate_threads_token(THREADS_CONFIG, HTTP, LOGGER)
    if not token_result.valid:
        update_post(record["post_id"], {"status": "failed", "error_message": token_result.error})
        print(f"[THREADS] Token invalid; publishing skipped safely: {token_result.status}")
        return

    try:
        # Re-check duplicate status immediately before the irreversible API call.
        second_duplicate = find_duplicate(generated_text, extra_texts=[topic.get("Instagram Article Draft", "")])
        if second_duplicate.is_duplicate and second_duplicate.matched_post_id != record["post_id"]:
            update_post(record["post_id"], {"status": "rejected", "error_message": "duplicate_detected_before_publish"})
            print(f"[THREADS] Duplicate detected before publish; skipped: {second_duplicate.matched_post_id}")
            return

        if content_type == "thread_series":
            external_ids = publish_thread_series(posts)
            external_id = ",".join(external_ids)
        else:
            external_id = publish_single_post(posts[0])
        update_post(
            record["post_id"],
            {
                "status": "published",
                "external_threads_id": external_id,
                "published_at": datetime.now(timezone.utc).isoformat(),
                "error_message": "",
            },
        )
    except Exception as exc:
        update_post(record["post_id"], {"status": "failed", "error_message": str(exc)})
        log_event(LOGGER, "threads_publish_failed", logging.ERROR, platform="threads", status="failed", error=str(exc), record_id=record["post_id"])
        print(f"[THREADS] Publish failed safely: {exc}")
        return

    print(f"\n{'=' * 60}")
    print("✅ Threads published!")
    print(f"{'=' * 60}\n")


def run_comment_collection():
    collected = collect_threads_comments(THREADS_CONFIG, HTTP, FLAGS)
    print(f"[THREADS] Comments collected: {collected}")


def main():
    parser = argparse.ArgumentParser(description="Safe Threads publishing and learning tools")
    parser.add_argument("--collect-comments", action="store_true", help="Collect Threads comments when ENABLE_THREADS_COMMENT_COLLECTION=true")
    parser.add_argument("--weekly-report", action="store_true", help="Generate a weekly Threads learning report")
    args = parser.parse_args()

    if args.collect_comments:
        run_comment_collection()
    elif args.weekly_report:
        path = generate_weekly_report(FLAGS)
        print(f"[THREADS] Weekly report saved: {path}")
    else:
        run_threads_pipeline()
        if FLAGS.enable_threads_comment_collection:
            run_comment_collection()


if __name__ == "__main__":
    main()
