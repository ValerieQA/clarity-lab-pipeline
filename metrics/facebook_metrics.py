"""
Facebook metrics collector for Clarity Lab Pipeline.

Attempts to fetch post reactions and comments via the Graph API.
Requires: FB_PAGE_TOKEN, FB_PAGE_ID.

Engagement metrics (reach, impressions) require additional Page Insights
permission. Reports clearly what is and isn't available.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger("facebook_metrics")

_BASE = "https://graph.facebook.com/v19.0"


def _get(url: str, params: dict) -> tuple[Optional[dict], Optional[str]]:
    try:
        import requests
        resp = requests.get(url, params=params, timeout=15)
        data = resp.json()
        if "error" in data:
            err = data["error"]
            return None, f"{err.get('code', '?')} {err.get('type', '')}: {err.get('message', '')}"
        return data, None
    except Exception as e:
        return None, str(e)


def collect(post_ids: Optional[list[str]] = None) -> list[dict]:
    """
    Return normalised metric objects for Facebook posts.

    post_ids: list of Facebook Post IDs (format: page_id_post_id).
    """
    token = os.environ.get("FB_PAGE_TOKEN", "")
    if not token:
        return [{
            "channel": "facebook",
            "metrics_available": False,
            "reason": "Missing environment variable: FB_PAGE_TOKEN",
            "action_required": "Add FB_PAGE_TOKEN to GitHub Actions secrets.",
        }]

    if not post_ids:
        return [{
            "channel": "facebook",
            "metrics_available": False,
            "reason": "No Facebook post IDs provided.",
            "action_required": "Ensure topics.csv contains 'Facebook Post ID' values.",
        }]

    results = []
    for post_id in post_ids:
        if not post_id:
            continue

        # Basic post data
        data, err = _get(
            f"{_BASE}/{post_id}",
            {"fields": "id,message,created_time,permalink_url", "access_token": token},
        )

        if err:
            results.append({
                "channel": "facebook",
                "post_id": post_id,
                "url": None,
                "published_at": None,
                "metrics_available": False,
                "reason": err,
                "errors": [err],
                "missing_permissions": ["pages_read_engagement"] if "permission" in err.lower() else [],
            })
            continue

        permalink    = data.get("permalink_url")
        created_time = data.get("created_time")

        # Reactions count
        react_data, react_err = _get(
            f"{_BASE}/{post_id}/reactions",
            {"summary": "true", "access_token": token},
        )
        likes = None
        if react_data:
            likes = react_data.get("summary", {}).get("total_count")

        # Comments count
        comm_data, comm_err = _get(
            f"{_BASE}/{post_id}/comments",
            {"summary": "true", "access_token": token},
        )
        comments_count = None
        if comm_data:
            comments_count = comm_data.get("summary", {}).get("total_count")

        # Insights (reach/impressions) — requires pages_read_engagement
        insights_data, insights_err = _get(
            f"{_BASE}/{post_id}/insights",
            {"metric": "post_impressions,post_reach", "access_token": token},
        )
        views = None
        missing_perms: list[str] = []
        if insights_err:
            if "permission" in insights_err.lower() or "190" in insights_err:
                missing_perms = ["pages_read_engagement — required for reach/impressions"]
            logger.warning("Facebook insights unavailable for %s: %s", post_id, insights_err)
        elif insights_data:
            for item in insights_data.get("data", []):
                if item.get("name") == "post_reach":
                    vals = item.get("values", [])
                    views = vals[-1].get("value") if vals else None

        results.append({
            "channel": "facebook",
            "post_id": post_id,
            "url": permalink,
            "published_at": created_time,
            "metrics_available": True,
            "metrics": {
                "likes": likes,
                "comments": comments_count,
                "shares": None,
                "views": views,
                "clicks": None,
            },
            "comments": [],
            "errors": [e for e in [react_err, comm_err] if e and "permission" not in (e or "").lower()],
            "missing_permissions": missing_perms,
        })

    return results or [{
        "channel": "facebook",
        "metrics_available": False,
        "reason": "No valid post IDs processed.",
        "action_required": "Check Facebook Post ID column in topics.csv.",
    }]
