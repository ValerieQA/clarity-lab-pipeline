"""
Wix metrics collector for Clarity Lab Pipeline.

The Wix REST API does not currently expose per-post analytics (views, likes,
comments) for Blog posts via a public endpoint. This collector reads what is
stored locally in topics.csv and returns a normalised object that honestly
reports what is and isn't available.

If Wix ever adds a public analytics API, the collect() function can be extended
to make live requests while keeping the same output schema.
"""

from __future__ import annotations

import csv
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger("wix_metrics")

TOPICS_FILE = Path(os.environ.get("TOPICS_FILE", "topics.csv"))

_WIX_API_NOTE = (
    "Wix Blog analytics are not available via the Wix REST API for automated collection. "
    "View post performance in the Wix dashboard: https://manage.wix.com/analytics/overview . "
    "This collector reports publication status only."
)


def collect(post_ids: Optional[list[str]] = None) -> list[dict]:
    """
    Return normalised metric objects for Wix blog posts.

    Reads Published URL and Wix Status from topics.csv.
    Engagement metrics (views, comments) are not available via API — reported honestly.
    """
    if not TOPICS_FILE.exists():
        return [{
            "channel": "wix",
            "metrics_available": False,
            "reason": f"topics.csv not found at {TOPICS_FILE}",
            "action_required": "Ensure topics.csv exists in the repository root.",
        }]

    results = []
    with TOPICS_FILE.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            wix_status = row.get("Wix Status", "").strip().lower()
            url        = (row.get("Published URL") or row.get("Website Published URL") or "").strip()
            post_id    = row.get("ID", "").strip()

            if post_ids and post_id not in post_ids:
                continue
            if not url and wix_status != "published":
                continue

            results.append({
                "channel": "wix",
                "post_id": post_id,
                "url": url or None,
                "published_at": row.get("Date Added", ""),
                "title": row.get("Topic / Working Title", ""),
                "metrics_available": False,
                "metrics": {
                    "likes": None,
                    "comments": None,
                    "shares": None,
                    "views": None,
                    "clicks": None,
                },
                "comments": [],
                "errors": [],
                "missing_permissions": [],
                "note": _WIX_API_NOTE,
            })

    if not results:
        return [{
            "channel": "wix",
            "metrics_available": False,
            "reason": "No published Wix posts found in topics.csv.",
            "action_required": "Ensure Wix posts have been published and URLs are recorded.",
            "note": _WIX_API_NOTE,
        }]

    return results
