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

def build_report() -> dict:
    inventory     = load_inventory(TOPICS_FILE)
    health        = run_health_check(TOPICS_FILE)
    topics        = _topics_this_week()
    channel_week  = _channel_week_summary(topics)
    threads_data  = _load_threads_data()
    comments_all  = _load_threads_comments()
    comments_week = _comments_this_week(comments_all)
    top_themes    = _top_themes(comments_week)
    avail_notes   = _channel_availability_notes(health)

    # Best / weakest topic by channel (simple heuristic: published = scored)
    published_titles = [t.get("Topic / Working Title", "") for t in topics
                        if t.get("Pipeline State", "").lower() == "completed"]
    failed_titles    = [t.get("Topic / Working Title", "") for t in topics
                        if t.get("Pipeline State", "").lower() in ("failed", "partial_failure")]

    # Threads-specific best performers from weekly report
    best_threads = threads_data.get("best_performing_posts", [])

    return {
        "report_type": "weekly",
        "report_date": TODAY.isoformat(),
        "week_start": WEEK_START.isoformat(),
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "topic_inventory": inventory,
        "pipeline_health_summary": {
            "overall_status": health["overall_status"],
            "token_issues": health["token_issues"],
            "missing_env": health["missing_env"],
        },
        "channel_performance": channel_week,
        "data_availability_notes": avail_notes,
        "threads_insights": {
            "comments_this_week": len(comments_week),
            "top_themes": top_themes,
            "best_performing_posts": best_threads[:3],
            "source": "threads_weekly_report",
        },
        "strategy_signals": {
            "published_topics": published_titles,
            "failed_topics": failed_titles,
            "comment_themes": top_themes,
            "note": (
                "Only Threads reaction data is currently available as a comment signal. "
                "Instagram/Facebook/Wix engagement metrics are not collected via API in this cycle."
                if not avail_notes else " | ".join(avail_notes)
            ),
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
    health_st  = report["pipeline_health_summary"]["overall_status"].upper()
    ch         = report["channel_performance"]
    threads    = report["threads_insights"]
    signals    = report["strategy_signals"]
    ops        = report["operational_issues"]

    lines = [
        f"# Clarity Lab — Weekly Strategy Report",
        f"**Week:** {ws} → {d}",
        "",
        f"**Pipeline status:** {health_st}  ",
        f"**Topic inventory:** {inv['remaining_topics']} remaining ({inv['status'].upper()})",
        "",
        "---",
        "",
        "## Content Published This Week",
        "",
    ]

    for channel, stats in ch.items():
        lines.append(f"**{channel}:** {stats['published_count']} published, {stats['failed_count']} failed")
        for title in stats["topics"]:
            lines.append(f"  - {title}")
    lines.append("")

    # Data availability
    if report["data_availability_notes"]:
        lines.append("## Data Availability Notes")
        lines.append("")
        for note in report["data_availability_notes"]:
            lines.append(f"> {note}")
        lines.append("")

    # Threads insights
    lines += [
        "## Channel Insights",
        "",
        "### Threads",
        f"- Comments this week: {threads['comments_this_week']}",
    ]
    if threads["top_themes"]:
        lines.append(f"- Recurring themes: {', '.join(threads['top_themes'])}")
    if threads["best_performing_posts"]:
        lines.append("- Best performing posts (by score):")
        for p in threads["best_performing_posts"]:
            preview = p.get("text_preview", "")[:80]
            lines.append(f"  - Score {p.get('score', 0)}: \"{preview}…\"")
    lines.append("")

    for ch_name in ["Instagram", "Facebook", "Wix"]:
        lines.append(f"### {ch_name}")
        matching = next(
            (n for n in report["data_availability_notes"] if ch_name.lower() in n.lower()), None
        )
        if matching:
            lines.append(f"> {matching}")
        else:
            stats = ch.get(ch_name, {})
            lines.append(f"- Published: {stats.get('published_count', 0)}, Failed: {stats.get('failed_count', 0)}")
        lines.append("")

    # Strategy signals
    lines += [
        "## Strategy Signals",
        "",
        f"**Note:** {signals['note']}",
        "",
    ]
    if signals["published_topics"]:
        lines.append("**Topics completed this week:**")
        for t in signals["published_topics"]:
            lines.append(f"- {t}")
        lines.append("")
    if signals["failed_topics"]:
        lines.append("**Topics that failed (need review):**")
        for t in signals["failed_topics"]:
            lines.append(f"- {t}")
        lines.append("")
    if signals["comment_themes"]:
        lines.append(f"**Recurring comment themes:** {', '.join(signals['comment_themes'])}")
        lines.append("")

    # Operational issues
    if ops["token_issues"] or ops["missing_env"]:
        lines.append("## Operational Issues — Action Required")
        lines.append("")
        for t in ops["token_issues"]:
            lines.append(f"- **{t['platform'].capitalize()} token**: {t['message']}")
            lines.append(f"  → {t['action']}")
        for m in ops["missing_env"]:
            lines.append(f"- **Missing secrets ({m['service']})**: {', '.join(m['missing_vars'])}")
            lines.append(f"  → {m['action']}")
        lines.append("")

    # Inventory
    lines.append("## Topic Inventory")
    lines.append("")
    lines.append(f"```\n{inventory_summary(inv)}\n```")

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
