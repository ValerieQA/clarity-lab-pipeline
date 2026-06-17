"""
Instagram metrics collector for Clarity Lab Pipeline.

Attempts to fetch basic media metrics via the Instagram Graph API.
Requires: IG_USER_ID, IG_TOKEN, and the instagram_manage_insights permission.

If permission is missing or token is invalid, returns a structured
unavailability report — never fakes data, never raises.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger("instagram_metrics")

_BASE = "https://graph.instagram.com/v19.0"

# Metrics that require instagram_manage_insights
INSIGHTS_METRICS = ["impressions", "reach", "likes_count", "comments_count", "shares"]


def _get(url: str, params: dict) -> tuple[Optional[dict], Optional[str]]:
    """GET request; returns (data, error_message)."""
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
    Return normalised metric objects for Instagram posts.

    post_ids: list of Instagram media IDs (Post ID column in topics.csv).
              If None, returns a no-data report explaining what is needed.
    """
    token = os.environ.get("IG_TOKEN", "")
    if not token:
        return [{
            "channel": "instagram",
            "metrics_available": False,
            "reason": "Missing environment variable: IG_TOKEN",
            "action_required": "Add IG_TOKEN to GitHub Actions secrets.",
        }]

    if not post_ids:
        return [{
            "channel": "instagram",
            "metrics_available": False,
            "reason": "No Instagram post IDs provided.",
            "action_required": (
                "Ensure topics.csv contains 'Instagram Post ID' values "
                "for published posts."
            ),
        }]

    results = []
    for media_id in post_ids:
        if not media_id:
            continue

        # Basic fields (no extra permission required)
        data, err = _get(
            f"{_BASE}/{media_id}",
            {"fields": "id,media_type,timestamp,permalink", "access_token": token},
        )

        if err:
            missing_perms = []
            if "permissions" in err.lower() or "OAuthException" in err:
                missing_perms = ["instagram_basic"]
            results.append({
                "channel": "instagram",
                "post_id": media_id,
                "url": None,
                "published_at": None,
                "metrics_available": False,
                "reason": err,
                "errors": [err],
                "missing_permissions": missing_perms,
            })
            continue

        permalink  = data.get("permalink")
        timestamp  = data.get("timestamp")

        # Attempt insights (may fail without instagram_manage_insights)
        insights_data, insights_err = _get(
            f"{_BASE}/{media_id}/insights",
            {"metric": ",".join(INSIGHTS_METRICS), "access_token": token},
        )

        metrics: dict = {k: None for k in ["likes", "comments", "shares", "views", "clicks"]}
        missing_perms: list[str] = []

        if insights_err:
            if "permission" in insights_err.lower() or "200" in insights_err:
                missing_perms = ["instagram_manage_insights"]
            logger.warning("Instagram insights unavailable for %s: %s", media_id, insights_err)
        elif insights_data:
            for item in insights_data.get("data", []):
                name  = item.get("name", "")
                value = item.get("values", [{}])[-1].get("value") if item.get("values") else item.get("value")
                if name == "impressions":
                    metrics["views"] = value
                elif name == "likes_count":
                    metrics["likes"] = value
                elif name == "comments_count":
                    metrics["comments"] = value
                elif name == "shares":
                    metrics["shares"] = value

        results.append({
            "channel": "instagram",
            "post_id": media_id,
            "url": permalink,
            "published_at": timestamp,
            "metrics_available": not bool(missing_perms),
            "metrics": metrics,
            "comments": [],
            "errors": [insights_err] if insights_err and not missing_perms else [],
            "missing_permissions": missing_perms,
        })

    return results or [{
        "channel": "instagram",
        "metrics_available": False,
        "reason": "No valid post IDs processed.",
        "action_required": "Check Instagram Post ID column in topics.csv.",
    }]
