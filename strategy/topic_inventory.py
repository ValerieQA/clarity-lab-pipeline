"""
Topic Inventory Monitor for Clarity Lab Pipeline.

Reads topics.csv and produces a structured inventory report.
Can be run standalone or imported by other modules.

Thresholds:
    CRITICAL : 0 unpublished topics remaining
    WARNING  : 5 or fewer
    NOTICE   : 10 or fewer
    HEALTHY  : > 10

Exit codes (when run as __main__):
    0  healthy / notice
    1  warning
    2  critical
"""

from __future__ import annotations

import csv
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

# Default path — can be overridden via TOPICS_FILE env var
DEFAULT_TOPICS_FILE = Path(__file__).resolve().parents[1] / "topics.csv"

THRESHOLD_CRITICAL = 0
THRESHOLD_WARNING  = 5
THRESHOLD_NOTICE   = 10

# Statuses that count as "done" (published or permanently failed)
PUBLISHED_STATUSES  = {"published", "complete", "completed"}
FAILED_STATUSES     = {"failed", "partial failure", "partial_failure", "error"}
READY_STATUSES      = {"ready", "pending", "queued", ""}   # empty = not started

# Publishing cadence used to estimate days left (topics per week)
DEFAULT_CADENCE_PER_WEEK = 3


def _normalise(value: str) -> str:
    return value.strip().lower()


def load_inventory(topics_file: Optional[Path] = None) -> dict:
    """
    Parse topics.csv and return a structured inventory dict.
    Never raises on missing file — returns a critical-status report instead.
    """
    path = topics_file or Path(os.environ.get("TOPICS_FILE", str(DEFAULT_TOPICS_FILE)))

    if not path.exists():
        return {
            "total_topics": 0,
            "published_topics": 0,
            "remaining_topics": 0,
            "failed_topics": 0,
            "days_left": 0,
            "next_topic": None,
            "status": "critical",
            "action_required": True,
            "message": f"topics.csv not found at {path}",
        }

    total = published = failed = ready = 0
    next_topic: Optional[str] = None

    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            total += 1
            status_raw = _normalise(row.get("Status", ""))
            pipeline_raw = _normalise(row.get("Pipeline State", ""))

            # Determine effective status: Pipeline State takes precedence when set
            effective = pipeline_raw if pipeline_raw else status_raw

            if effective in PUBLISHED_STATUSES:
                published += 1
            elif effective in FAILED_STATUSES:
                failed += 1
            else:
                # Counts as remaining/ready
                ready += 1
                if next_topic is None:
                    next_topic = row.get("Topic / Working Title", "").strip() or row.get("ID", "")

    cadence = DEFAULT_CADENCE_PER_WEEK
    days_left = int((ready / cadence) * 7) if cadence > 0 else 0

    if ready == THRESHOLD_CRITICAL:
        level = "critical"
        action = True
        msg = "No unpublished topics remaining. Publishing is blocked. Strategy rebuild required immediately."
    elif ready <= THRESHOLD_WARNING:
        level = "warning"
        action = True
        msg = f"Only {ready} topic(s) remaining. Strategy rebuild should begin now."
    elif ready <= THRESHOLD_NOTICE:
        level = "notice"
        action = True
        msg = f"{ready} topics remaining (~{days_left} days). Plan the next strategy cycle."
    else:
        level = "healthy"
        action = False
        msg = f"{ready} topics remaining (~{days_left} days). Inventory is healthy."

    return {
        "total_topics": total,
        "published_topics": published,
        "remaining_topics": ready,
        "failed_topics": failed,
        "days_left": days_left,
        "next_topic": next_topic,
        "status": level,
        "action_required": action,
        "message": msg,
    }


def format_summary(inventory: dict) -> str:
    """Human-readable one-block summary for emails and logs."""
    lines = [
        "=== Clarity Lab — Topic Inventory ===",
        f"Status        : {inventory['status'].upper()}",
        f"Total topics  : {inventory['total_topics']}",
        f"Published     : {inventory['published_topics']}",
        f"Remaining     : {inventory['remaining_topics']}",
        f"Failed        : {inventory['failed_topics']}",
        f"Days left     : ~{inventory['days_left']}",
    ]
    if inventory.get("next_topic"):
        lines.append(f"Next topic    : {inventory['next_topic']}")
    lines.append("")
    lines.append(inventory["message"])
    return "\n".join(lines)


if __name__ == "__main__":
    inventory = load_inventory()
    print(json.dumps(inventory, indent=2))
    print()
    print(format_summary(inventory))

    if inventory["action_required"]:
        # Optionally send email when run in CI
        if os.environ.get("SEND_EMAIL_ALERTS", "").lower() == "true":
            from notifications.email_reporter import send_critical_alert
            send_critical_alert(format_summary(inventory))

    status = inventory["status"]
    if status == "critical":
        sys.exit(2)
    elif status == "warning":
        sys.exit(1)
    sys.exit(0)
