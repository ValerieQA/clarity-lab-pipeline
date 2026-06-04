"""
Clarity Lab — Threads Pipeline
Production-safe draft-first Threads workflow.
"""

from __future__ import annotations

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
from threads_store import append_post, draft_record, find_duplicate

# ============================================================
# CONFIG
# ============================================================

import os

OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
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


def truncate_to_limit(text, limit=500):
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
    client = OpenAI(api_key=OPENAI_API_KEY, max_retries=FLAGS.http_max_retries, timeout=FLAGS.http_timeout_seconds)
    base_prompt = load_prompt(THREADS_PROMPT_PATH)
    prompt = f"""
{base_prompt}

Content type: {content_type}
Topic: {topic_row['Topic / Working Title']}
Core observation: {topic_row['Core Observation']}
Audience question: {topic_row['Audience Question']}
"""

    print(f"[GPT] Generating Threads content (type: {content_type})...")
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=600,
        temperature=0.8,
    )

    text = response.choices[0].message.content.strip()
    print("[GPT] Threads content generated")
    return text


def posts_from_raw(raw_content: str, content_type: str) -> list[str]:
    if content_type == "thread_series":
        posts = parse_series_sections(raw_content)
    else:
        posts = [truncate_to_limit(clean_markdown(raw_content))]
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

    duplicate = find_duplicate("\n\n".join(posts), extra_texts=[topic.get("Instagram Article Draft", "")])
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
        record = draft_record(source_topic, "\n\n".join(posts), content_type, content_type, status="rejected", error_message="duplicate_detected")
        append_post(record)
        print(f"[THREADS] Duplicate detected ({duplicate.similarity:.2f}); draft rejected and not published")
        return

    record = draft_record(source_topic, "\n\n".join(posts), content_type, content_type, status="draft")
    append_post(record)
    print(f"[THREADS] Draft saved: {record['post_id']}")

    if FLAGS.dry_run or not FLAGS.enable_threads_publishing:
        log_event(LOGGER, "threads_publish_skipped", platform="threads", status="skipped", details={"dry_run": FLAGS.dry_run, "enabled": FLAGS.enable_threads_publishing, "post_id": record["post_id"]})
        print("[THREADS] Publishing skipped. Set ENABLE_THREADS_PUBLISHING=true to publish after review.")
        return

    token_result = validate_threads_token(THREADS_CONFIG, HTTP, LOGGER)
    if not token_result.valid:
        failed = draft_record(source_topic, "\n\n".join(posts), content_type, content_type, status="failed", error_message=token_result.error)
        append_post(failed)
        print(f"[THREADS] Token invalid; publishing skipped safely: {token_result.status}")
        return

    try:
        if content_type == "thread_series":
            external_ids = publish_thread_series(posts)
            external_id = ",".join(external_ids)
        else:
            external_id = publish_single_post(posts[0])
        published = draft_record(source_topic, "\n\n".join(posts), content_type, content_type, status="published")
        published["external_threads_id"] = external_id
        published["published_at"] = datetime.now(timezone.utc).isoformat()
        append_post(published)
    except Exception as exc:
        failed = draft_record(source_topic, "\n\n".join(posts), content_type, content_type, status="failed", error_message=str(exc))
        append_post(failed)
        log_event(LOGGER, "threads_publish_failed", logging.ERROR, platform="threads", status="failed", error=str(exc))
        print(f"[THREADS] Publish failed safely: {exc}")
        return

    print(f"\n{'=' * 60}")
    print("✅ Threads published!")
    print(f"   Topic: {topic['Topic / Working Title']}")
    print(f"   Type: {content_type}")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    run_threads_pipeline()
