"""
Threads metrics collector for Clarity Lab Pipeline.

Reads from existing local data (threads_posts.csv, threads_comments.csv,
threads_weekly_reports/) — no additional API calls needed since the
threads_workflow.yml already collects posts and comments.

Returns normalised metric objects per post.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

THREADS_POSTS    = Path("data/threads_posts.csv")
THREADS_COMMENTS = Path("data/threads_comments.csv")
WEEKLY_REPORTS   = Path("data/threads_weekly_reports")


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def collect(post_ids: Optional[list[str]] = None) -> list[dict]:
    """
    Return normalised metric objects for Threads posts.

    If post_ids is provided, filter to those posts only.
    Metrics are derived from local stored data only — no live API call.
    If live API metrics (likes, replies) are needed, the threads_workflow
    must be extended to collect them; this collector reports what is stored.
    """
    posts    = _read_csv(THREADS_POSTS)
    comments = _read_csv(THREADS_COMMENTS)

    # Build comment count index
    comment_counts: dict[str, int] = defaultdict(int)
    comment_texts:  dict[str, list[str]] = defaultdict(list)
    for c in comments:
        pid = c.get("post_id", "")
        if pid:
            comment_counts[pid] += 1
            text = c.get("comment_text", "").strip()
            if text:
                comment_texts[pid].append(text)

    results = []
    for post in posts:
        post_id     = post.get("post_id", "")
        external_id = post.get("external_id", "")
        if post_ids and post_id not in post_ids:
            continue

        results.append({
            "channel": "threads",
            "post_id": post_id,
            "external_id": external_id,
            "url": f"https://www.threads.net/t/{external_id}" if external_id else None,
            "published_at": post.get("published_at", "") or post.get("created_at", ""),
            "metrics_available": True,
            "metrics": {
                "likes": None,        # not stored locally; requires live API + permission
                "comments": comment_counts.get(post_id, 0),
                "shares": None,
                "views": None,
                "clicks": None,
            },
            "comments": comment_texts.get(post_id, [])[:10],  # cap at 10 for reports
            "errors": [],
            "missing_permissions": [
                "threads_manage_insights — required for likes/views (not collected in current workflow)"
            ] if comment_counts.get(post_id, 0) == 0 else [],
        })

    if not results:
        return [{
            "channel": "threads",
            "metrics_available": False,
            "reason": "No Threads posts found in data/threads_posts.csv",
            "action_required": "Ensure threads_workflow.yml has run and stored posts.",
        }]

    return results
