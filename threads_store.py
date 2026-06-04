"""Persistent Threads draft storage and lightweight duplicate detection."""

from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

THREADS_DB = Path("data/threads_posts.csv")
THREADS_FIELDS = [
    "post_id",
    "source_type",
    "source_topic",
    "category",
    "opening_type",
    "generated_text",
    "generated_at",
    "approved_by",
    "published_at",
    "status",
    "external_threads_id",
    "error_message",
    "comments",
    "engagement_metrics",
    "themes",
]
VALID_STATUSES = {"draft", "approved", "scheduled", "published", "archived", "rejected", "failed"}


@dataclass
class DuplicateResult:
    is_duplicate: bool
    similarity: float = 0.0
    matched_post_id: str = ""
    matched_text: str = ""


def normalize_text(text: str) -> str:
    text = re.sub(r"[^a-z0-9\s]", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize_text(a), normalize_text(b)).ratio()


def ensure_store(path: Path = THREADS_DB) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with path.open("w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=THREADS_FIELDS).writeheader()


def read_posts(path: Path = THREADS_DB) -> list[dict[str, str]]:
    ensure_store(path)
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def append_post(post: dict[str, str], path: Path = THREADS_DB) -> None:
    ensure_store(path)
    row = {field: post.get(field, "") for field in THREADS_FIELDS}
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=THREADS_FIELDS)
        writer.writerow(row)



def write_posts(rows: list[dict[str, str]], path: Path = THREADS_DB) -> None:
    ensure_store(path)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=THREADS_FIELDS)
        writer.writeheader()
        for post in rows:
            writer.writerow({field: post.get(field, "") for field in THREADS_FIELDS})


def update_post(post_id: str, updates: dict[str, str], path: Path = THREADS_DB) -> None:
    rows = read_posts(path)
    updated = False
    for row in rows:
        if row.get("post_id") == post_id:
            row.update({field: value for field, value in updates.items() if field in THREADS_FIELDS})
            updated = True
            break
    if not updated:
        raise ValueError(f"Threads post not found: {post_id}")
    write_posts(rows, path)


def published_thread_count_on(day: date | None = None, path: Path = THREADS_DB) -> int:
    target = day or datetime.now(timezone.utc).date()
    count = 0
    for row in read_posts(path):
        if row.get("status") != "published":
            continue
        published_at = row.get("published_at", "")
        try:
            published_day = datetime.fromisoformat(published_at.replace("Z", "+00:00")).date()
        except ValueError:
            continue
        if published_day != target:
            continue
        external_ids = [item for item in row.get("external_threads_id", "").split(",") if item.strip()]
        count += max(1, len(external_ids))
    return count

def create_post_id(source_topic: str, text: str) -> str:
    digest = hashlib.sha256(f"{source_topic}\n{text}".encode("utf-8")).hexdigest()[:16]
    return f"threads_{digest}"


def draft_record(source_topic: str, generated_text: str, category: str, opening_type: str, status: str = "draft", error_message: str = "") -> dict[str, str]:
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid Threads status: {status}")
    return {
        "post_id": create_post_id(source_topic, generated_text),
        "source_type": "topic",
        "source_topic": source_topic,
        "category": category,
        "opening_type": opening_type,
        "generated_text": generated_text,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "approved_by": "",
        "published_at": "",
        "status": status,
        "external_threads_id": "",
        "error_message": error_message,
        "comments": "[]",
        "engagement_metrics": "{}",
        "themes": "[]",
    }


def find_duplicate(text: str, extra_texts: list[str] | None = None, threshold: float = 0.88, path: Path = THREADS_DB) -> DuplicateResult:
    candidates = [(row.get("post_id", ""), row.get("generated_text", "")) for row in read_posts(path)]
    candidates.extend(("article_social", t) for t in (extra_texts or []) if t)
    best = DuplicateResult(False)
    for post_id, candidate in candidates:
        score = similarity(text, candidate)
        if score > best.similarity:
            best = DuplicateResult(score >= threshold, score, post_id, candidate[:200])
    return best
