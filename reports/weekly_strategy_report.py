"""
Weekly Strategy Report for Clarity Lab Pipeline.

Aggregates the last 7 days of publishing, available channel metrics,
Threads comments/posts data, and topic inventory into a strategic report.

Outputs:
    data/reports/weekly/weekly_report_YYYY-MM-DD.json
    data/reports/weekly/weekly_report_YYYY-MM-DD.md
    Email via notifications/email_reporter.py

Run:
    python -m reports.weekly_strategy_report
"""

from __future__ import annotations

import csv
import json
import logging
import os
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from notifications.email_reporter import send_weekly_report
from strategy.pipeline_health import run_health_check
from strategy.topic_inventory import load_inventory, format_summary as inventory_summary

logger = logging.getLogger("weekly_strategy_report")

TOPICS_FILE      = Path(os.environ.get("TOPICS_FILE", "topics.csv"))
THREADS_POSTS    = Path("data/threads_posts.csv")
THREADS_COMMENTS = Path("data/threads_comments.csv")
WEEKLY_REPORTS   = Path("data/threads_weekly_reports")
REPORTS_DIR      = Path("data/reports/weekly")
TODAY            = date.today()
WEEK_START       = TODAY - timedelta(days=7)


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------

def _topics_this_week() -> list[dict]:
    if not TOPICS_FILE.exists():
        return []
    results = []
    with TOPICS_FILE.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            date_added = row.get("Date Added", "").strip()
            pipeline_state = row.get("Pipeline State", "").strip().lower()
            # Include topics added this week OR with any publish activity
            try:
                d = date.fromisoformat(date_added) if date_added else None
            except ValueError:
                d = None
            has_activity = pipeline_state not in ("", "draft")
            in_window = d and WEEK_START <= d <= TODAY
            if in_window or has_activity:
                results.append(row)
    return results


def _channel_week_summary(topics: list[dict]) -> dict[str, dict]:
    channels = {
        "Wix":       ("Wix Status",       "Website Published URL"),
        "Instagram": ("Instagram Status", "Instagram Published URL"),
        "Facebook":  ("Facebook Status",  "FB Message"),
        "Threads":   ("Threads Status",   "Threads External ID"),
    }
    summary = {}
    for ch, (status_col, _) in channels.items():
        published = [t for t in topics if t.get(status_col, "").strip().lower() == "published"]
        failed    = [t for t in topics if t.get(status_col, "").strip().lower() in ("failed", "error")]
        summary[ch] = {
            "published_count": len(published),
            "failed_count": len(failed),
            "topics": [t.get("Topic / Working Title", "") for t in published],
        }
    return summary


def _load_threads_data() -> dict:
    """Load latest Threads weekly JSON report if available."""
    if not WEEKLY_REPORTS.exists():
        return {}
    reports = sorted(WEEKLY_REPORTS.glob("threads_weekly_report_*.json"))
    if not reports:
        return {}
    latest = reports[-1]
    try:
        return json.loads(latest.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("Could not load Threads weekly report %s: %s", latest, e)
        return {}


def _load_threads_comments() -> list[dict]:
    if not THREADS_COMMENTS.exists():
        return []
    with THREADS_COMMENTS.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _comments_this_week(comments: list[dict]) -> list[dict]:
    results = []
    for c in comments:
        raw = c.get("created_at", "") or c.get("collected_at", "")
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00")) if raw else None
        except ValueError:
            dt = None
        if dt and dt.date() >= WEEK_START:
            results.append(c)
    return results


def _top_themes(comments: list[dict], n: int = 5) -> list[str]:
    STOPWORDS = {"the", "a", "an", "is", "it", "in", "of", "to", "and", "that",
                 "this", "for", "i", "you", "we", "are", "was", "be", "have",
                 "not", "with", "as", "at", "by", "from", "or", "but", "clarity"}
    words: Counter = Counter()
    for c in comments:
        text = c.get("comment_text", "").lower()
        for word in text.split():
            word = word.strip(".,!?;:\"'")
            if len(word) > 3 and word not in STOPWORDS:
                words[word] += 1
    return [w for w, _ in words.most_common(n)]


def _channel_availability_notes(health: dict) -> list[str]:
    """Return explanatory notes for channels where data is unavailable."""
    notes = []
    for m in health.get("missing_env", []):
        svc = m["service"]
        if svc == "instagram":
            notes.append(
                "Instagram performance data unavailable because required environment "
                "variables are missing: " + ", ".join(m["missing_vars"]) + ". "
                "Action required: add these secrets to GitHub Actions."
            )
        elif svc == "facebook":
            notes.append(
                "Facebook performance data unavailable — missing env: " + ", ".join(m["missing_vars"])
            )
        elif svc == "wix":
            notes.append(
                "Wix performance data unavailable — missing env: " + ", ".join(m["missing_vars"])
            )
    for t in health.get("token_issues", []):
        if t["status"] == "blocked":
            notes.append(
                f"{t['platform'].capitalize()} data unavailable — token expired. Action: {t['action']}"
            )
    return notes


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------

def _threads_posts_this_week() -> list[dict]:
    """Return Threads posts published during the current week window."""
    posts_file = THREADS_POSTS
    if not posts_file.exists():
        return []
    results = []
    with posts_file.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            raw = (row.get("published_at") or row.get("created_at") or "").strip()[:10]
            try:
                d = date.fromisoformat(raw) if raw else None
            except ValueError:
                d = None
            if d and WEEK_START <= d <= TODAY:
                results.append(row)
    return results


def _confidence_level(comments_count: int, channels_with_data: int) -> tuple[str, str]:
    """Return (level, reason) for strategy confidence."""
    if comments_count >= 10 and channels_with_data >= 3:
        return "Medium", "Multiple channels with data; Threads comment signal present."
    if comments_count >= 5 or channels_with_data >= 2:
        return "Low", "Limited data: only 1-2 channels have engagement information."
    return "Low", "Insufficient data: fewer than 5 comments collected; most channel metrics unavailable."


def build_report() -> dict:
    inventory       = load_inventory(TOPICS_FILE)
    health          = run_health_check(TOPICS_FILE)
    topics          = _topics_this_week()
    channel_week    = _channel_week_summary(topics)
    threads_data    = _load_threads_data()
    comments_all    = _load_threads_comments()
    comments_week   = _comments_this_week(comments_all)
    threads_this_wk = _threads_posts_this_week()
    top_themes      = _top_themes(comments_week)
    avail_notes     = _channel_availability_notes(health)

    published_titles = [t.get("Topic / Working Title", "") for t in topics
                        if t.get("Pipeline State", "").lower() == "completed"]
    failed_titles    = [t.get("Topic / Working Title", "") for t in topics
                        if t.get("Pipeline State", "").lower() in ("failed", "partial_failure")]

    # Threads best posts — only from this week to avoid contradiction
    # If no posts this week, use historical with clear label
    best_threads_this_week = []
    best_threads_historical = []
    all_best = threads_data.get("best_performing_posts", [])
    this_week_ids = {r.get("post_id", "") or r.get("external_id", "") for r in threads_this_wk}
    for p in all_best[:5]:
        pid = p.get("post_id", "") or p.get("external_threads_id", "")
        if pid in this_week_ids:
            best_threads_this_week.append(p)
        else:
            best_threads_historical.append(p)

    channels_with_data = sum(1 for ch in ["wix", "instagram", "facebook", "threads"]
                             if channel_week.get(ch.capitalize(), {}).get("published_count", 0) > 0
                             or (ch == "threads" and len(threads_this_wk) > 0))
    confidence, confidence_reason = _confidence_level(len(comments_week), channels_with_data)

    # Strategy interpretation — based only on available facts
    observed_patterns: list[str] = []
    weak_signals: list[str] = []
    not_yet_knowable: list[str] = []

    if top_themes:
        observed_patterns.append(f"Audience comment themes this week: {', '.join(top_themes[:3])}")
    if len(comments_week) > 0 and len(comments_week) < 5:
        weak_signals.append(f"Only {len(comments_week)} Threads comment(s) this week — pattern not statistically meaningful.")
    if len(comments_week) == 0:
        not_yet_knowable.append("No Threads comments collected this week. Cannot determine audience resonance.")
    not_yet_knowable.append("Instagram engagement (likes, reach, saves) — requires instagram_manage_insights permission.")
    not_yet_knowable.append("Facebook reach and impressions — requires pages_read_engagement permission.")
    not_yet_knowable.append("Wix article views — not available via Wix REST API. Check Wix dashboard manually.")
    if not observed_patterns:
        observed_patterns.append("No clear patterns observable from available data this week.")

    # Build action items from health
    action_items = health.get("action_items", [])
    if failed_titles:
        action_items = [f"Review failed topic(s): {', '.join(failed_titles[:3])}"] + action_items

    return {
        "report_type": "weekly",
        "report_date": TODAY.isoformat(),
        "week_start": WEEK_START.isoformat(),
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "topic_inventory": inventory,
        "pipeline_health_summary": {
            "overall_status": health["overall_status"],
            "critical_reasons": health.get("critical_reasons", []),
            "action_items": action_items,
            "token_issues": health["token_issues"],
            "missing_env": health["missing_env"],
            "permissions_audit": health.get("permissions_audit", []),
        },
        "channel_performance": channel_week,
        "data_availability_notes": avail_notes,
        "threads_insights": {
            "posts_this_week": len(threads_this_wk),
            "comments_this_week": len(comments_week),
            "top_themes": top_themes,
            "best_performing_this_week": best_threads_this_week[:3],
            "best_performing_historical": best_threads_historical[:3],
            "all_scores_zero": all(p.get("score", 0) == 0 for p in all_best) if all_best else True,
        },
        "facts": {
            "published_topics": published_titles,
            "failed_topics": failed_titles,
            "threads_posts_this_week": len(threads_this_wk),
            "comments_this_week": len(comments_week),
            "comment_themes": top_themes,
        },
        "interpretation": {
            "observed_patterns": observed_patterns,
            "weak_signals": weak_signals,
            "not_yet_knowable": not_yet_knowable,
            "strategic_note": (
                "Insufficient data for strategic conclusions this week. "
                "Only Threads comment signal is partially available."
                if not top_themes else
                f"Early signal from {len(comments_week)} Threads comment(s). "
                "Not sufficient to draw firm strategy conclusions."
            ),
            "confidence": confidence,
            "confidence_reason": confidence_reason,
        },
        "operational_issues": {
            "token_issues": health["token_issues"],
            "missing_env": health["missing_env"],
        },
    }


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def to_markdown(report: dict) -> str:
    d          = report["report_date"]
    ws         = report["week_start"]
    inv        = report["topic_inventory"]
    health     = report["pipeline_health_summary"]
    health_st  = health["overall_status"].upper()
    ch         = report["channel_performance"]
    threads    = report["threads_insights"]
    facts      = report["facts"]
    interp     = report["interpretation"]
    ops        = report["operational_issues"]
    critical_reasons = health.get("critical_reasons", [])
    action_items     = health.get("action_items", [])
    permissions      = health.get("permissions_audit", [])

    lines = [
        "# Clarity Lab — Weekly Strategy Report",
        f"**Week:** {ws} → {d}",
        "",
        f"**Pipeline status:** {health_st}  ",
        f"**Topic inventory:** {inv['remaining_topics']} remaining ({inv['status'].upper()})",
        "",
    ]

    # --- Critical Reasons ---
    if critical_reasons and health["overall_status"] in ("critical", "blocked"):
        lines += ["## Critical Reasons", ""]
        for i, reason in enumerate(critical_reasons, 1):
            lines.append(f"{i}. {reason}")
        lines.append("")

    # --- Action Required ---
    lines += ["## Action Required", ""]
    if action_items:
        for item in action_items:
            lines.append(f"- [ ] {item}")
    else:
        lines.append("No manual action required this week.")
    lines.append("")

    # --- Facts ---
    lines += ["## Facts", ""]
    lines.append("_What actually happened this week, based on available data._")
    lines.append("")

    # Content published
    lines.append("**Content published this week:**")
    any_published = False
    for channel, stats in ch.items():
        count = stats["published_count"]
        fail  = stats["failed_count"]
        lines.append(f"- {channel}: {count} published, {fail} failed")
        for title in stats["topics"]:
            lines.append(f"  - {title}")
        if count > 0:
            any_published = True

    # Threads separate
    lines.append(f"- Threads (via separate workflow): {threads['posts_this_week']} posts this week")
    lines.append("")

    if facts["published_topics"]:
        lines.append("**Completed topics:**")
        for t in facts["published_topics"]:
            lines.append(f"- {t}")
        lines.append("")
    if facts["failed_topics"]:
        lines.append("**Failed topics (need review):**")
        for t in facts["failed_topics"]:
            lines.append(f"- {t}")
        lines.append("")

    lines.append(f"**Threads engagement this week:**")
    lines.append(f"- Posts published this week: {threads['posts_this_week']}")
    lines.append(f"- Comments collected this week: {threads['comments_this_week']}")
    if facts["comment_themes"]:
        lines.append(f"- Comment themes: {', '.join(facts['comment_themes'])}")
    lines.append("")

    # --- Channel Insights ---
    lines += ["## Channel Insights", ""]

    lines.append("### Threads")
    lines.append(f"- Posts this week: {threads['posts_this_week']}")
    lines.append(f"- Comments this week: {threads['comments_this_week']}")
    if threads["best_performing_this_week"]:
        lines.append("- Best performing posts this week (by comment count):")
        for p in threads["best_performing_this_week"]:
            score   = p.get("score", 0)
            preview = p.get("text_preview", "")[:80]
            lines.append(f"  - Score {score}: \"{preview}…\"")
    elif threads["best_performing_historical"]:
        lines.append("- No posts from this week had engagement data.")
        lines.append("- Historical signal (from previous weeks):")
        for p in threads["best_performing_historical"][:2]:
            preview = p.get("text_preview", "")[:80]
            lines.append(f"  - \"{preview}…\"")
        if threads.get("all_scores_zero"):
            lines.append("- **No meaningful performance signal yet.** All scores = 0.")
    else:
        lines.append("- No Threads post data available for this period.")
    lines.append("")

    for ch_name in ["Instagram", "Facebook", "Wix"]:
        lines.append(f"### {ch_name}")
        stats = ch.get(ch_name, {})
        lines.append(f"- Published this week: {stats.get('published_count', 0)}")
        # Find permission note from audit
        perm = next((p for p in permissions if p["channel"] == ch_name), None)
        if perm:
            lines.append(f"- Metrics: **{perm['metrics']}** — {perm['metrics_note']}")
            lines.append(f"- Comments: **{perm['comments']}** — {perm['comments_note']}")
        lines.append("")

    # --- Permissions & Data Availability ---
    lines += ["## Permissions & Data Availability", ""]
    if permissions:
        lines.append("| Channel | Publishing | Metrics | Comments | Notes |")
        lines.append("|---|---|---|---|---|")
        for p in permissions:
            note = p["metrics_note"][:65] if len(p["metrics_note"]) > 65 else p["metrics_note"]
            lines.append(
                f"| {p['channel']} | {p['publishing']} | {p['metrics']} | {p['comments']} | {note} |"
            )
        lines.append("")
    else:
        lines.append("_Permissions audit not available._")
        lines.append("")

    # --- Interpretation ---
    lines += ["## Interpretation", ""]
    lines.append("_Based on available data only. Labeled by confidence level._")
    lines.append("")

    lines.append("### Observed Patterns")
    for pattern in interp["observed_patterns"]:
        lines.append(f"- {pattern}")
    lines.append("")

    if interp["weak_signals"]:
        lines.append("### Weak Signals")
        for s in interp["weak_signals"]:
            lines.append(f"- {s}")
        lines.append("")

    lines.append("### What Is Not Yet Knowable")
    for u in interp["not_yet_knowable"]:
        lines.append(f"- {u}")
    lines.append("")

    lines.append("### Strategic Interpretation")
    lines.append(interp["strategic_note"])
    lines.append("")

    lines.append("### Confidence")
    lines.append(f"**{interp['confidence']}**")
    lines.append(f"Reason: {interp['confidence_reason']}")
    lines.append("")

    # --- Topic Inventory ---
    lines += ["## Topic Inventory", ""]
    lines.append(f"- Remaining: {inv['remaining_topics']} topics")
    lines.append(f"- Publishing cadence: {inv.get('cadence_per_week', 3)} topics/week "
                 f"({inv.get('cadence_source', 'default')})")
    lines.append(f"- Estimated runway: ~{inv['days_left']} days")
    lines.append(f"- Status: **{inv['status'].upper()}** — {inv['message']}")
    lines.append("")

    # --- Operational Issues ---
    if ops["token_issues"] or ops["missing_env"]:
        lines += ["## Operational Issues — Action Required", ""]
        for t in ops["token_issues"]:
            lines.append(f"- **{t['platform'].capitalize()} token**: {t['message']}")
            lines.append(f"  → {t['action']}")
        for m in ops["missing_env"]:
            if m["service"] in ("wix", "instagram", "facebook", "threads", "openai"):
                lines.append(f"- **Missing secrets ({m['service']})**: {', '.join(m['missing_vars'])}")
                lines.append(f"  → {m['action']}")
        lines.append("")

    # --- Recommended Next Actions ---
    lines += ["## Recommended Next Actions", ""]
    next_actions: list[str] = list(action_items)

    # Add strategy-specific recommendations
    if inv["status"] in ("warning", "critical"):
        next_actions.append("Begin next strategy cycle planning — topic inventory is low")
    if not threads["posts_this_week"] and threads["comments_this_week"] == 0:
        next_actions.append("Investigate Threads publishing — no posts or comments this week")
    if not any_published:
        next_actions.append("Investigate why no content was published across any channel this week")
    if "instagram_manage_insights" in str(permissions):
        next_actions.append("Consider requesting instagram_manage_insights permission in Meta App Review")
    if interp["confidence"] == "Low":
        next_actions.append("Wait for more data before changing content strategy — current signal is insufficient")
    if facts["failed_topics"]:
        next_actions.append(f"Review and retry failed topic(s): {', '.join(facts['failed_topics'][:2])}")
    if not next_actions:
        next_actions.append("No action required — pipeline is operating normally")

    for i, a in enumerate(next_actions[:7], 1):
        lines.append(f"{i}. {a}")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Save & send
# ---------------------------------------------------------------------------

def save_report(report: dict, md: str) -> tuple[Path, Path]:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    base = REPORTS_DIR / f"weekly_report_{TODAY.isoformat()}"
    json_path = base.with_suffix(".json")
    md_path   = base.with_suffix(".md")
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(md, encoding="utf-8")
    return json_path, md_path


def run(send_email: bool = True) -> dict:
    report = build_report()
    md     = to_markdown(report)
    save_report(report, md)
    logger.info("Weekly report saved for %s", TODAY.isoformat())

    if send_email:
        ok = send_weekly_report(md, week_of=WEEK_START)
        if not ok:
            logger.error("Failed to send weekly report email.")

    return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    send = os.environ.get("SEND_EMAIL_ALERTS", "true").lower() == "true"
    result = run(send_email=send)
    print(f"Weekly report: {result['week_start']} → {result['report_date']}")
    print(f"Pipeline status: {result['pipeline_health_summary']['overall_status']}")
    print(f"Threads comments this week: {result['threads_insights']['comments_this_week']}")
