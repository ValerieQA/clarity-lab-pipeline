"""
Daily Report for Clarity Lab Pipeline.

Aggregates today's publishing activity from topics.csv, pipeline health,
topic inventory, and any available channel metrics into a structured report.

Outputs:
    data/reports/daily/daily_report_YYYY-MM-DD.json
    data/reports/daily/daily_report_YYYY-MM-DD.md
    Email via notifications/email_reporter.py

Run:
    python -m reports.daily_report
"""

from __future__ import annotations

import csv
import json
import logging
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from notifications.email_reporter import send_daily_report
from strategy.pipeline_health import run_health_check, format_summary as health_summary
from strategy.topic_inventory import load_inventory, format_summary as inventory_summary

logger = logging.getLogger("daily_report")

TOPICS_FILE   = Path(os.environ.get("TOPICS_FILE", "topics.csv"))
REPORTS_DIR   = Path("data/reports/daily")
TODAY         = date.today()


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------

def _collect_today_topics() -> list[dict]:
    """Return topics where Date Added == today or with recent pipeline activity."""
    if not TOPICS_FILE.exists():
        return []

    today_str = TODAY.isoformat()
    results = []

    with TOPICS_FILE.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            date_added = row.get("Date Added", "").strip()
            pipeline_state = row.get("Pipeline State", "").strip().lower()
            publish_status = row.get("Publish Status Code", "").strip()
            wix = row.get("Wix Status", "").strip().lower()
            ig  = row.get("Instagram Status", "").strip().lower()
            fb  = row.get("Facebook Status", "").strip().lower()
            th  = row.get("Threads Status", "").strip().lower()

            # Include if any publish activity exists or published today
            has_activity = any([wix, ig, fb, th, pipeline_state not in ("", "draft")])
            if date_added == today_str or has_activity:
                results.append({
                    "id": row.get("ID", ""),
                    "title": row.get("Topic / Working Title", ""),
                    "date_added": date_added,
                    "status": row.get("Status", ""),
                    "pipeline_state": pipeline_state,
                    "wix_status": wix,
                    "instagram_status": ig,
                    "facebook_status": fb,
                    "threads_status": th,
                    "published_url": row.get("Published URL", "") or row.get("Website Published URL", ""),
                    "instagram_url": row.get("Instagram Published URL", ""),
                    "publish_status_code": publish_status,
                    "errors": row.get("Publication Errors", "") or row.get("Last Error", ""),
                    "retry_available": row.get("Retry Available", ""),
                })

    return results


def _channel_summary(topics: list[dict]) -> dict[str, dict]:
    """Return per-channel counts for the given topic set."""
    channels = {"wix": "wix_status", "instagram": "instagram_status",
                "facebook": "facebook_status", "threads": "threads_status"}
    summary = {}
    for ch, field in channels.items():
        published = [t for t in topics if t[field] == "published"]
        failed    = [t for t in topics if t[field] in ("failed", "error")]
        partial   = [t for t in topics if t[field] in ("partial_failure", "partial failure")]
        queued    = [t for t in topics if t[field] in ("queued", "pending", "")]
        summary[ch] = {
            "published": len(published),
            "failed": len(failed),
            "partial": len(partial),
            "queued": len(queued),
            "published_urls": [t.get("published_url") or t.get("instagram_url") for t in published if t.get("published_url") or t.get("instagram_url")],
        }
    return summary


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------

def build_report() -> dict:
    inventory = load_inventory(TOPICS_FILE)
    health    = run_health_check(TOPICS_FILE)
    topics    = _collect_today_topics()
    channels  = _channel_summary(topics)

    failed_topics   = [t for t in topics if t["pipeline_state"] in ("failed", "partial_failure") or any(
        t[f] in ("failed", "error") for f in ("wix_status", "instagram_status", "facebook_status", "threads_status")
    )]
    retry_available = [t for t in topics if t.get("retry_available", "").strip().lower() in ("true", "1", "yes")]

    return {
        "report_type": "daily",
        "report_date": TODAY.isoformat(),
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "topic_inventory": inventory,
        "pipeline_health": {
            "overall_status": health["overall_status"],
            "critical_reasons": health.get("critical_reasons", []),
            "action_items": health.get("action_items", []),
            "channels": health["channels"],
            "token_issues": health["token_issues"],
            "missing_env": health["missing_env"],
            "permissions_audit": health.get("permissions_audit", []),
        },
        "today_activity": {
            "total_topics_active": len(topics),
            "failed_topics": len(failed_topics),
            "retry_queue": len(retry_available),
            "channel_breakdown": channels,
        },
        "topics": topics,
    }


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def _status_icon(status: str) -> str:
    return {"published": "✓", "failed": "✗", "error": "✗", "partial_failure": "~",
            "partial failure": "~", "queued": "·", "": "·"}.get(status.lower(), "?")


def to_markdown(report: dict) -> str:
    d             = report["report_date"]
    health        = report["pipeline_health"]
    health_status = health["overall_status"].upper()
    inv           = report["topic_inventory"]
    activity      = report["today_activity"]
    critical_reasons = health.get("critical_reasons", [])
    action_items     = health.get("action_items", [])
    permissions      = health.get("permissions_audit", [])
    failed_topics    = [t for t in report["topics"] if t.get("pipeline_state") in
                        ("failed", "partial_failure") or
                        any(t.get(f) in ("failed", "error")
                            for f in ("wix_status", "instagram_status", "facebook_status", "threads_status"))]

    lines = [
        f"# Clarity Lab — Daily Report {d}",
        "",
        f"**Pipeline status:** {health_status}  ",
        f"**Topic inventory:** {inv['remaining_topics']} remaining — {inv['status'].upper()}",
        "",
    ]

    # --- Critical Reasons (only shown when status warrants it) ---
    if critical_reasons and health["overall_status"] in ("critical", "blocked"):
        lines += ["## Critical Reasons", ""]
        for i, reason in enumerate(critical_reasons, 1):
            lines.append(f"{i}. {reason}")
        lines.append("")

    # --- Action Required (always present) ---
    lines += ["## Action Required", ""]
    if action_items or failed_topics:
        for item in action_items:
            lines.append(f"- [ ] {item}")
        for t in failed_topics[:5]:
            lines.append(f"- [ ] Review failed topic: **{t['title']}** — {(t.get('errors') or 'no error detail')[:80]}")
        if not action_items and not failed_topics:
            lines.append("No manual action required today.")
    else:
        lines.append("No manual action required today.")
    lines.append("")

    # --- Publishing Activity ---
    lines += [
        "## Publishing Activity",
        "",
        f"- Topics with activity: {activity['total_topics_active']}",
        f"- Failed: {activity['failed_topics']}",
        f"- In retry queue: {activity['retry_queue']}",
        "",
        "## Channel Breakdown",
        "",
    ]

    for ch, stats in activity["channel_breakdown"].items():
        lines.append(f"### {ch.capitalize()}")
        lines.append(f"- Published: {stats['published']}")
        lines.append(f"- Failed: {stats['failed']}")
        lines.append(f"- Partial: {stats['partial']}")
        if stats["published_urls"]:
            for url in stats["published_urls"]:
                lines.append(f"  - {url}")
        lines.append("")

    # --- Topic table ---
    topics = report["topics"]
    if topics:
        lines += ["## Topic Status", ""]
        lines.append("| ID | Title | Wix | IG | FB | Threads | Errors |")
        lines.append("|---|---|---|---|---|---|---|")
        for t in topics:
            errors = (t.get("errors") or "")[:60]
            lines.append(
                f"| {t['id']} | {t['title'][:40]} "
                f"| {_status_icon(t['wix_status'])} "
                f"| {_status_icon(t['instagram_status'])} "
                f"| {_status_icon(t['facebook_status'])} "
                f"| {_status_icon(t['threads_status'])} "
                f"| {errors} |"
            )
        lines.append("")

    # --- Permissions & Data Availability ---
    lines += ["## Permissions & Data Availability", ""]
    if permissions:
        lines.append("| Channel | Publishing | Metrics | Comments | Notes |")
        lines.append("|---|---|---|---|---|")
        for p in permissions:
            metrics_note = p["metrics_note"][:60] if len(p["metrics_note"]) > 60 else p["metrics_note"]
            lines.append(
                f"| {p['channel']} | {p['publishing']} | {p['metrics']} | {p['comments']} | {metrics_note} |"
            )
        lines.append("")
        lines.append("_Full permission details: see [docs/PERMISSIONS_AND_METRICS.md](../docs/PERMISSIONS_AND_METRICS.md)_")
    else:
        lines.append("_Permissions audit not available._")
    lines.append("")

    # --- Topic Inventory ---
    lines += ["## Topic Inventory", ""]
    lines.append(f"- Remaining: {inv['remaining_topics']} topics")
    lines.append(f"- Publishing cadence: {inv.get('cadence_per_week', 3)} topics/week ({inv.get('cadence_source', 'default')})")
    lines.append(f"- Estimated runway: ~{inv['days_left']} days")
    if inv.get("next_topic"):
        lines.append(f"- Next topic: {inv['next_topic']}")
    lines.append(f"- Status: **{inv['status'].upper()}** — {inv['message']}")
    lines.append("")

    # --- Recommended Next Actions ---
    lines += ["## Recommended Next Actions for Today", ""]
    next_actions = list(action_items)  # start from health action items
    if failed_topics:
        next_actions.insert(0, f"Review {len(failed_topics)} failed topic(s) and retry if appropriate")
    if not next_actions:
        if inv["status"] in ("warning", "critical"):
            next_actions.append("Begin planning next strategy cycle — topic inventory is low")
        else:
            next_actions.append("No action required — pipeline is operating normally")
    for i, a in enumerate(next_actions[:6], 1):
        lines.append(f"{i}. {a}")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Save & send
# ---------------------------------------------------------------------------

def save_report(report: dict, md: str) -> tuple[Path, Path]:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    base = REPORTS_DIR / f"daily_report_{TODAY.isoformat()}"
    json_path = base.with_suffix(".json")
    md_path   = base.with_suffix(".md")
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(md, encoding="utf-8")
    return json_path, md_path


def run(send_email: bool = True) -> dict:
    report = build_report()
    md     = to_markdown(report)
    json_path, md_path = save_report(report, md)
    logger.info("Daily report saved: %s", json_path)

    if send_email:
        ok = send_daily_report(md, report_date=TODAY)
        if not ok:
            logger.error("Failed to send daily report email.")
            # Do not raise — reporting failure must not block other operations

    return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    send = os.environ.get("SEND_EMAIL_ALERTS", "true").lower() == "true"
    result = run(send_email=send)
    print(f"Report date    : {result['report_date']}")
    print(f"Pipeline status: {result['pipeline_health']['overall_status']}")
    print(f"Inventory      : {result['topic_inventory']['remaining_topics']} topics remaining ({result['topic_inventory']['status']})")
