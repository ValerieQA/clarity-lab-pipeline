"""
Daily Report for Clarity Lab Pipeline.

Morning operational briefing: Did content publish? Did something fail?
Does the owner need to do anything? Target: readable in 5-10 seconds.

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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from notifications.email_reporter import send_daily_report
from strategy.pipeline_health import run_health_check, format_summary as health_summary
from strategy.topic_inventory import load_inventory, format_summary as inventory_summary

logger = logging.getLogger("daily_report")

TOPICS_FILE = Path(os.environ.get("TOPICS_FILE", "topics.csv"))
REPORTS_DIR = Path("data/reports/daily")
TODAY       = date.today()

_STATUS_ICON = {
    "healthy":  "🟢",
    "warning":  "🟡",
    "critical": "🔴",
    "blocked":  "🔴",
    "unknown":  "⚪",
}
_CHANNEL_ICON = {
    "published":       "✅",
    "failed":          "❌",
    "error":           "❌",
    "partial_failure": "⚠️",
    "partial failure": "⚠️",
    "queued":          "⏳",
    "pending":         "⏳",
    "skipped":         "⏭️",
    "":                "⚪",
}


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------

def _collect_today_topics() -> list[dict]:
    """Return topics with any publish activity (not draft/empty)."""
    if not TOPICS_FILE.exists():
        return []

    results = []
    with TOPICS_FILE.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pipeline_state = row.get("Pipeline State", "").strip().lower()
            wix = row.get("Wix Status", "").strip().lower()
            ig  = row.get("Instagram Status", "").strip().lower()
            fb  = row.get("Facebook Status", "").strip().lower()
            th  = row.get("Threads Status", "").strip().lower()

            has_activity = any([wix, ig, fb, th, pipeline_state not in ("", "draft")])
            if not has_activity:
                continue

            errors = (row.get("Publication Errors", "") or row.get("Last Error", "")).strip()
            results.append({
                "id":              row.get("ID", ""),
                "title":           row.get("Topic / Working Title", ""),
                "date_added":      row.get("Date Added", ""),
                "status":          row.get("Status", ""),
                "pipeline_state":  pipeline_state,
                "wix_status":      wix,
                "instagram_status": ig,
                "facebook_status": fb,
                "threads_status":  th,
                "published_url":   row.get("Published URL", "") or row.get("Website Published URL", ""),
                "instagram_url":   row.get("Instagram Published URL", ""),
                "publish_status_code": row.get("Publish Status Code", ""),
                "errors":          errors,
                "retry_available": row.get("Retry Available", ""),
            })

    return results


def _channel_summary(topics: list[dict]) -> dict[str, dict]:
    channels = {
        "wix":       "wix_status",
        "instagram": "instagram_status",
        "facebook":  "facebook_status",
        "threads":   "threads_status",
    }
    summary = {}
    for ch, field in channels.items():
        published = [t for t in topics if t[field] == "published"]
        failed    = [t for t in topics if t[field] in ("failed", "error")]
        partial   = [t for t in topics if t[field] in ("partial_failure", "partial failure")]
        skipped   = [t for t in topics if t[field] in ("skipped",)]
        summary[ch] = {
            "published":      len(published),
            "failed":         len(failed),
            "partial":        len(partial),
            "skipped":        len(skipped),
            "published_urls": [
                t.get("published_url") or t.get("instagram_url")
                for t in published
                if t.get("published_url") or t.get("instagram_url")
            ],
        }
    return summary


def _infer_failure_stage(topic: dict) -> tuple[str, str]:
    """
    Return (stage_description, error_detail) for a failed/partial topic.
    Infers where the pipeline broke by looking at per-channel statuses.
    """
    succeeded   = []
    failed_at   = []
    not_reached = []

    for ch, field in [("Wix", "wix_status"), ("Instagram", "instagram_status"),
                      ("Facebook", "facebook_status"), ("Threads", "threads_status")]:
        val = topic.get(field, "")
        if val == "published":
            succeeded.append(ch)
        elif val in ("failed", "error"):
            failed_at.append(ch)
        elif val in ("partial_failure", "partial failure"):
            failed_at.append(f"{ch} (partial)")
        elif val in ("skipped",):
            not_reached.append(f"{ch} (skipped)")
        elif not val:
            not_reached.append(f"{ch} (status not recorded)")

    parts = []
    if succeeded:
        parts.append(f"Succeeded: {', '.join(succeeded)}")
    if failed_at:
        parts.append(f"Failed at: {', '.join(failed_at)}")
    if not_reached:
        parts.append(f"Not reached: {', '.join(not_reached)}")

    stage = "; ".join(parts) if parts else "Stage unknown"

    errors = topic.get("errors", "").strip()
    if not errors:
        errors = (
            "Error detail not recorded in topics.csv. "
            "Check GitHub Actions logs for the run that processed this topic."
        )

    return stage, errors


def _data_quality_assessment(health: dict, topics: list[dict]) -> dict:
    """
    Assess what data is available vs missing.
    Returns score (0-100), available list, missing list, confidence level.
    """
    available = []
    missing   = []
    score     = 0

    # Publishing data — always available from topics.csv
    published_any = any(
        t.get(f) == "published"
        for t in topics
        for f in ("wix_status", "instagram_status", "facebook_status")
    )
    if topics:
        available.append("Publishing status (topics.csv)")
        score += 25
    else:
        missing.append("Publishing data (topics.csv empty or missing)")

    # Threads posts data
    threads_posts = Path("data/threads_posts.csv")
    if threads_posts.exists():
        available.append("Threads post history (data/threads_posts.csv)")
        score += 15
    else:
        missing.append("Threads post history (data/threads_posts.csv not found)")

    # Threads comments
    threads_comments = Path("data/threads_comments.csv")
    if threads_comments.exists():
        available.append("Threads comments (data/threads_comments.csv)")
        score += 10
    else:
        missing.append("Threads comments (data/threads_comments.csv not found)")

    # Instagram metrics
    perms = {p["channel"]: p for p in health.get("permissions_audit", [])}
    ig_perm = perms.get("Instagram", {})
    if ig_perm.get("metrics") == "available":
        available.append("Instagram engagement metrics")
        score += 20
    else:
        missing.append("Instagram engagement (likes, reach, saves) — needs instagram_manage_insights permission")

    # Facebook metrics
    fb_perm = perms.get("Facebook", {})
    if fb_perm.get("metrics") == "available":
        available.append("Facebook reach and impressions")
        score += 10
    elif fb_perm.get("metrics") == "partial":
        available.append("Facebook reactions (partial — reach unavailable)")
        score += 5
        missing.append("Facebook reach/impressions — needs pages_read_engagement permission")
    else:
        missing.append("Facebook engagement metrics — needs pages_read_engagement permission")

    # Wix analytics
    wix_perm = perms.get("Wix", {})
    if wix_perm.get("metrics") == "available":
        available.append("Wix article views")
        score += 15
    else:
        missing.append("Wix article views — not available via Wix REST API (check dashboard manually)")

    # Topic inventory
    available.append("Topic inventory (remaining count, cadence)")
    score += 5

    # Confidence
    if score >= 70:
        confidence = "High"
    elif score >= 40:
        confidence = "Medium"
    else:
        confidence = "Low"

    return {
        "score":      min(score, 100),
        "available":  available,
        "missing":    missing,
        "confidence": confidence,
    }


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------

def build_report() -> dict:
    inventory = load_inventory(TOPICS_FILE)
    health    = run_health_check(TOPICS_FILE)
    topics    = _collect_today_topics()
    channels  = _channel_summary(topics)

    failed_topics = [
        t for t in topics
        if t["pipeline_state"] in ("failed", "partial_failure")
        or any(t[f] in ("failed", "error") for f in ("wix_status", "instagram_status", "facebook_status", "threads_status"))
    ]
    retry_available = [t for t in topics if t.get("retry_available", "").strip().lower() in ("true", "1", "yes")]

    # Enrich failed topics with stage diagnostics
    for t in failed_topics:
        t["failure_stage"], t["failure_error"] = _infer_failure_stage(t)

    dqa = _data_quality_assessment(health, topics)

    return {
        "report_type":    "daily",
        "report_date":    TODAY.isoformat(),
        "generated_at":   datetime.now(tz=timezone.utc).isoformat(),
        "topic_inventory": inventory,
        "pipeline_health": {
            "overall_status":   health["overall_status"],
            "critical_reasons": health.get("critical_reasons", []),
            "action_items":     health.get("action_items", []),
            "channels":         health["channels"],
            "token_issues":     health["token_issues"],
            "missing_env":      health["missing_env"],
            "permissions_audit": health.get("permissions_audit", []),
        },
        "today_activity": {
            "total_topics_active": len(topics),
            "failed_topics":       len(failed_topics),
            "retry_queue":         len(retry_available),
            "channel_breakdown":   channels,
        },
        "topics":         topics,
        "failed_topics":  failed_topics,
        "data_quality":   dqa,
    }


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def _icon(status: str) -> str:
    return _STATUS_ICON.get(status.lower(), "⚪")


def _ch_icon(status: str) -> str:
    return _CHANNEL_ICON.get(status.lower(), "❓")


def to_markdown(report: dict) -> str:
    d       = report["report_date"]
    health  = report["pipeline_health"]
    inv     = report["topic_inventory"]
    act     = report["today_activity"]
    dqa     = report["data_quality"]
    topics  = report["topics"]
    failed  = report["failed_topics"]

    overall_icon  = _icon(health["overall_status"])
    inv_icon      = _icon(inv["status"])
    dqa_icon      = "🟢" if dqa["score"] >= 70 else ("🟡" if dqa["score"] >= 40 else "🔴")
    action_needed = bool(health.get("critical_reasons") or health.get("action_items") or failed)
    action_icon   = "🔴" if action_needed else "🟢"

    ch_stats = act["channel_breakdown"]
    total_published = sum(v["published"] for v in ch_stats.values())
    total_failed    = sum(v["failed"] + v["partial"] for v in ch_stats.values())

    # ── Executive Summary ──────────────────────────────────────────────────
    lines = [
        f"# Clarity Lab — Daily Report {d}",
        "",
        "## At a Glance",
        "",
        f"{overall_icon} **Publishing:** {health['overall_status'].upper()}  ",
        f"{inv_icon} **Topic Inventory:** {inv['status'].upper()} ({inv['remaining_topics']} topics left)  ",
        f"{dqa_icon} **Data Quality:** {dqa['confidence']} ({dqa['score']}/100)  ",
        f"{action_icon} **Action Required:** {'YES' if action_needed else 'NO'}  ",
        "",
        "**Today:**  ",
        f"{'✅' if total_published > 0 else '⚪'} {total_published} published  ",
        f"{'⚠️' if total_failed > 0 else '✅'} {total_failed} failed  ",
        "",
    ]

    # ── Action Required (near top, visible) ────────────────────────────────
    lines += ["## 🔴 Action Required" if action_needed else "## Action Required", ""]

    critical_reasons = health.get("critical_reasons", [])
    action_items     = health.get("action_items", [])

    if critical_reasons and health["overall_status"] in ("critical", "blocked"):
        lines += ["**Critical issues:**", ""]
        for i, reason in enumerate(critical_reasons, 1):
            lines.append(f"{i}. {reason}")
        lines.append("")

    if action_items or failed:
        for item in action_items:
            lines.append(f"- [ ] {item}")
        for t in failed[:5]:
            stage = t.get("failure_stage", "stage unknown")
            lines.append(f"- [ ] Review failed topic: **{t['title']}** — {stage}")
    else:
        lines.append("No manual action required today.")
    lines.append("")

    # ── Channel Status ─────────────────────────────────────────────────────
    lines += ["## Channel Status", ""]

    for ch_name, ch_key in [("Wix", "wix"), ("Instagram", "instagram"),
                             ("Facebook", "facebook"), ("Threads", "threads")]:
        stats = ch_stats.get(ch_key, {})
        pub   = stats.get("published", 0)
        fail  = stats.get("failed", 0) + stats.get("partial", 0)

        ch_health = next((c for c in health["channels"] if c["channel"] == ch_name), None)
        ch_status = ch_health["status"] if ch_health else "unknown"
        ch_icon   = _icon(ch_status)

        lines.append(f"### {ch_icon} {ch_name}")
        lines.append(f"{'✅' if pub > 0 else '⚪'} Published: {pub}")
        if fail:
            lines.append(f"⚠️ Failed/partial: {fail}")

        # Published URLs
        for url in stats.get("published_urls", [])[:3]:
            if url:
                lines.append(f"  - {url}")

        # Permission/metrics note
        perm = next((p for p in health.get("permissions_audit", []) if p["channel"] == ch_name), None)
        if perm:
            met = perm["metrics"]
            met_icon = "✅" if met == "available" else ("🟡" if met == "partial" else "⚪")
            lines.append(f"{met_icon} Metrics: {met}")
        lines.append("")

    # ── Failed Topic Diagnostics (Bug 2) ───────────────────────────────────
    if failed:
        lines += ["## Failed Topic Diagnostics", ""]
        for t in failed:
            lines.append(f"### ❌ {t['title']}")
            lines.append(f"- **Stage:** {t.get('failure_stage', 'unknown')}")
            lines.append(f"- **Error:** {t.get('failure_error', 'No error detail recorded.')}")
            if t.get("retry_available", "").lower() in ("true", "1", "yes"):
                lines.append("- **Retry available:** Yes")
            lines.append("")

    # ── Data Quality Assessment ────────────────────────────────────────────
    lines += [f"## Data Quality Assessment ({dqa['score']}/100)", ""]
    lines.append(f"**Confidence:** {dqa['confidence']}")
    lines.append("")
    if dqa["available"]:
        lines.append("**Available:**")
        for item in dqa["available"]:
            lines.append(f"- ✅ {item}")
        lines.append("")
    if dqa["missing"]:
        lines.append("**Missing:**")
        for item in dqa["missing"]:
            lines.append(f"- ⚪ {item}")
        lines.append("")

    # ── Topic Inventory ────────────────────────────────────────────────────
    lines += ["## Topic Inventory", ""]
    lines.append(f"- Remaining: {inv['remaining_topics']} topics")
    lines.append(f"- Publishing cadence: {inv.get('cadence_per_week', 3)} topics/week ({inv.get('cadence_source', 'default')})")
    lines.append(f"- Estimated runway: ~{inv['days_left']} days")
    if inv.get("next_topic"):
        lines.append(f"- Next topic: {inv['next_topic']}")
    lines.append(f"- Status: **{inv['status'].upper()}** — {inv['message']}")
    lines.append("")

    # ── Permissions & Data Availability ───────────────────────────────────
    permissions = health.get("permissions_audit", [])
    if permissions:
        lines += ["## Permissions & Data Availability", ""]
        for p in permissions:
            pub_icon = "✅" if p["publishing"] == "available" else "🔴"
            met_icon = "✅" if p["metrics"] == "available" else ("🟡" if p["metrics"] == "partial" else "⚪")
            com_icon = "✅" if p["comments"] == "available" else ("🟡" if p["comments"] == "partial" else "⚪")
            lines.append(f"**{p['channel']}:** {pub_icon} Publishing · {met_icon} Metrics ({p['metrics']}) · {com_icon} Comments ({p['comments']})")
        lines.append("")
        lines.append("_Full permission details: [docs/PERMISSIONS_AND_METRICS.md](../docs/PERMISSIONS_AND_METRICS.md)_")
        lines.append("")

    # ── Recommended Next Actions ───────────────────────────────────────────
    lines += ["## Recommended Next Actions", ""]
    next_actions: list[str] = list(action_items)
    if failed:
        next_actions.insert(0, f"Review {len(failed)} failed topic(s) and retry if appropriate")
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
    base      = REPORTS_DIR / f"daily_report_{TODAY.isoformat()}"
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

    return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    send = os.environ.get("SEND_EMAIL_ALERTS", "true").lower() == "true"
    result = run(send_email=send)
    print(f"Report date    : {result['report_date']}")
    print(f"Pipeline status: {result['pipeline_health']['overall_status']}")
    print(f"Inventory      : {result['topic_inventory']['remaining_topics']} topics remaining ({result['topic_inventory']['status']})")
    print(f"Data quality   : {result['data_quality']['score']}/100 ({result['data_quality']['confidence']})")
