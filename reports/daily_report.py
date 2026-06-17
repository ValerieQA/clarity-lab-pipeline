"""
Daily Report for Clarity Lab Pipeline.

Cockpit-style operational briefing. Target: readable in 10 seconds.
Answers: Did publishing work? Do I need to do anything today?

Daily = cockpit. Weekly = investigation.

Pipeline schedule:
  Mon / Wed / Fri: Main content pipeline (Blog + Instagram + Facebook)
  Tue / Thu / Sat: Stories pipeline (Instagram Stories only, not tracked in topics.csv)
  Sun:             No publishing — report only

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
from strategy.pipeline_health import run_health_check
from strategy.topic_inventory import load_inventory

logger = logging.getLogger("daily_report")

TOPICS_FILE = Path(os.environ.get("TOPICS_FILE", "topics.csv"))
REPORTS_DIR = Path("data/reports/daily")
TODAY       = date.today()

# Mon=0, Wed=2, Fri=4 → main content pipeline
# Tue=1, Thu=3, Sat=5 → stories pipeline
_CONTENT_DAYS = {0, 2, 4}
_STORIES_DAYS = {1, 3, 5}

_STATUS_ICON = {
    "healthy":  "🟢",
    "warning":  "🟡",
    "critical": "🔴",
    "blocked":  "🔴",
    "unknown":  "⚪",
}

# Data quality scoring formula (transparent, owner-readable)
# Sum = 100 pts maximum
DQ_FORMULA = {
    "publishing_data":      {"max": 25, "label": "Publishing data (topics.csv)"},
    "threads_posts":        {"max": 10, "label": "Threads post history"},
    "threads_comments":     {"max": 10, "label": "Threads comments collected"},
    "instagram_metrics":    {"max": 25, "label": "Instagram engagement metrics"},
    "facebook_metrics":     {"max": 15, "label": "Facebook reach & impressions"},
    "topic_inventory":      {"max": 10, "label": "Topic inventory & cadence"},
    "business_impact_data": {"max":  5, "label": "Business impact data (followers, visits)"},
}

# Why each missing data source matters and whether owner can fix it today
_WHY_IT_MATTERS = {
    "instagram_metrics": {
        "impact":         "Cannot determine which topics resonate with Instagram audience.",
        "priority":       "Medium",
        "can_fix_today":  "Yes",
        "action":         "Submit Meta App Review: Business Settings → App → Permissions → request instagram_manage_insights.",
    },
    "facebook_metrics": {
        "impact":         "Cannot measure Facebook post reach or impressions — only reactions visible.",
        "priority":       "Low",
        "can_fix_today":  "Yes",
        "action":         "Request pages_read_engagement in Meta App Review.",
    },
    "threads_metrics": {
        "impact":         "Cannot measure Threads post reach or impressions.",
        "priority":       "Low",
        "can_fix_today":  "Yes",
        "action":         "Request threads_manage_insights in Meta App Review.",
    },
    "wix_analytics": {
        "impact":         "Cannot measure article views automatically.",
        "priority":       "Low",
        "can_fix_today":  "No — Wix REST API does not expose analytics.",
        "action":         "Check Wix dashboard manually at wix.com/dashboard.",
    },
}


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------

def _today_schedule() -> str:
    dow = TODAY.weekday()
    if dow in _CONTENT_DAYS:
        return "content"
    if dow in _STORIES_DAYS:
        return "stories"
    return "none"


def _collect_topics() -> list[dict]:
    """Return all topics that have pipeline activity (not draft/empty)."""
    if not TOPICS_FILE.exists():
        return []

    results = []
    with TOPICS_FILE.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pipeline_state = row.get("Pipeline State", "").strip().lower()
            if pipeline_state in ("", "draft"):
                continue
            wix = row.get("Wix Status", "").strip().lower()
            ig  = row.get("Instagram Status", "").strip().lower()
            fb  = row.get("Facebook Status", "").strip().lower()
            th  = row.get("Threads Status", "").strip().lower()
            errors = (row.get("Publication Errors", "") or row.get("Last Error", "")).strip()
            results.append({
                "id":               row.get("ID", ""),
                "title":            row.get("Topic / Working Title", ""),
                "date_added":       row.get("Date Added", ""),
                "pipeline_state":   pipeline_state,
                "wix_status":       wix,
                "instagram_status": ig,
                "facebook_status":  fb,
                "threads_status":   th,
                "published_url":    row.get("Published URL", "") or row.get("Website Published URL", ""),
                "instagram_url":    row.get("Instagram Published URL", ""),
                "publish_status_code": row.get("Publish Status Code", ""),
                "errors":           errors,
                "retry_available":  row.get("Retry Available", ""),
            })
    return results


def _classify_topics(topics: list[dict]) -> dict:
    """
    Separate topics into: complete, partial, failed, pending.

    partial = some channels published, some didn't (pipeline_state partial_failure)
    failed  = pipeline_state failed AND no channels succeeded
    complete = pipeline_state completed
    pending  = no final state yet
    """
    complete = []
    partial  = []
    failed   = []
    pending  = []

    for t in topics:
        ps = t["pipeline_state"]
        any_published = any(
            t[f] == "published"
            for f in ("wix_status", "instagram_status", "facebook_status", "threads_status")
        )
        all_failed = all(
            t[f] in ("failed", "error", "")
            for f in ("wix_status", "instagram_status", "facebook_status")
        ) and not any_published

        if ps == "completed":
            complete.append(t)
        elif ps == "partial_failure" or (any_published and not ps == "completed"):
            # Some channels succeeded → partial
            t_partial = dict(t)
            t_partial["failure_stage"], t_partial["failure_error"] = _infer_failure_stage(t)
            partial.append(t_partial)
        elif ps == "failed" or all_failed:
            t_fail = dict(t)
            t_fail["failure_stage"], t_fail["failure_error"] = _infer_failure_stage(t)
            failed.append(t_fail)
        else:
            pending.append(t)

    return {"complete": complete, "partial": partial, "failed": failed, "pending": pending}


def _infer_failure_stage(topic: dict) -> tuple[str, str]:
    """Return (stage_description, error_detail) for a failed/partial topic."""
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
            not_reached.append(f"{ch} skipped")
        elif not val:
            not_reached.append(f"{ch} not reached")

    parts = []
    if succeeded:
        parts.append(f"Succeeded: {', '.join(succeeded)}")
    if failed_at:
        parts.append(f"Failed at: {', '.join(failed_at)}")
    if not_reached:
        parts.append(f"Not reached: {', '.join(not_reached)}")

    stage  = "; ".join(parts) if parts else "Stage unknown"
    errors = topic.get("errors", "").strip()
    if not errors:
        errors = (
            "Error detail not recorded in topics.csv. "
            "Check GitHub Actions logs for the run that processed this topic "
            f"(topic ID: {topic.get('id', 'unknown')})."
        )
    return stage, errors


def _data_quality(health: dict) -> dict:
    """
    Calculate data quality score using transparent formula.
    Each category has a defined max; points are awarded or not.
    Formula is shown in the report so owners understand the score.
    """
    perms = {p["channel"]: p for p in health.get("permissions_audit", [])}
    scores: dict[str, int] = {}

    # Publishing data
    scores["publishing_data"] = DQ_FORMULA["publishing_data"]["max"] if TOPICS_FILE.exists() else 0

    # Threads posts file
    scores["threads_posts"] = DQ_FORMULA["threads_posts"]["max"] if Path("data/threads_posts.csv").exists() else 0

    # Threads comments (non-empty)
    tc_path = Path("data/threads_comments.csv")
    if tc_path.exists():
        try:
            rows = sum(1 for _ in tc_path.open())
            scores["threads_comments"] = DQ_FORMULA["threads_comments"]["max"] if rows > 1 else 0
        except Exception:
            scores["threads_comments"] = 0
    else:
        scores["threads_comments"] = 0

    # Instagram metrics
    ig = perms.get("Instagram", {})
    if ig.get("metrics") == "available":
        scores["instagram_metrics"] = DQ_FORMULA["instagram_metrics"]["max"]
    elif ig.get("metrics") == "partial":
        scores["instagram_metrics"] = DQ_FORMULA["instagram_metrics"]["max"] // 2
    else:
        scores["instagram_metrics"] = 0

    # Facebook metrics
    fb = perms.get("Facebook", {})
    if fb.get("metrics") == "available":
        scores["facebook_metrics"] = DQ_FORMULA["facebook_metrics"]["max"]
    elif fb.get("metrics") == "partial":
        scores["facebook_metrics"] = DQ_FORMULA["facebook_metrics"]["max"] // 3  # reactions only
    else:
        scores["facebook_metrics"] = 0

    # Topic inventory (always available if topics.csv exists)
    scores["topic_inventory"] = DQ_FORMULA["topic_inventory"]["max"] if TOPICS_FILE.exists() else 0

    # Business impact data (placeholder — always 0 for now)
    scores["business_impact_data"] = 0

    total = sum(scores.values())
    confidence = "High" if total >= 70 else ("Medium" if total >= 40 else "Low")

    # Build breakdown for display
    breakdown: list[dict] = []
    for key, cfg in DQ_FORMULA.items():
        earned = scores[key]
        breakdown.append({
            "key":   key,
            "label": cfg["label"],
            "max":   cfg["max"],
            "score": earned,
            "available": earned > 0,
        })

    return {
        "total":      total,
        "max":        100,
        "confidence": confidence,
        "breakdown":  breakdown,
    }


def _owner_summary(health: dict, inv: dict, classified: dict) -> str:
    """Generate natural-language owner summary (2-4 sentences)."""
    parts = []

    status = health["overall_status"]
    if status == "healthy":
        parts.append("System is operating normally.")
    elif status == "warning":
        parts.append("System has minor issues — review Action Required section.")
    else:
        parts.append(f"System has critical issues requiring immediate attention.")

    # Publishing status
    published_channels = sum(
        1 for c in health["channels"]
        if c["channel"] != "Threads" and c["status"] == "healthy"
    )
    if published_channels >= 2:
        parts.append("Content is publishing correctly.")

    # Partial / failed
    if classified["partial"]:
        t = classified["partial"][0]
        parts.append(
            f"One topic published partially — \"{t['title']}\" requires review "
            f"({t.get('failure_stage', 'see details')})."
        )
    elif classified["failed"]:
        n = len(classified["failed"])
        parts.append(f"{n} topic(s) failed to publish and need immediate attention.")

    # Explicit no-action signal
    if not health.get("action_items") and not classified["failed"] and not classified["partial"]:
        parts.append("No urgent intervention required today.")

    # Main limitation
    ig_perm = next((p for p in health.get("permissions_audit", []) if p["channel"] == "Instagram"), None)
    if ig_perm and ig_perm.get("metrics") != "available":
        parts.append(
            "Main current limitation: Instagram insights unavailable — "
            "cannot determine which content performs best."
        )

    return " ".join(parts)


def _actionable_items(health: dict, classified: dict) -> list[dict]:
    """
    Return actionable items with specific next steps.
    Each item: {emoji, title, reason, action, severity}
    """
    items: list[dict] = []

    # Token issues — most critical
    for t in health.get("token_issues", []):
        if t["status"] in ("blocked", "critical"):
            items.append({
                "emoji":    "🔴",
                "title":    f"{t['platform'].capitalize()} token issue",
                "reason":   t["message"],
                "action":   t["action"],
                "severity": "critical",
            })
        elif t["status"] == "warning":
            items.append({
                "emoji":    "🟡",
                "title":    f"{t['platform'].capitalize()} token expiring",
                "reason":   t["message"],
                "action":   t["action"],
                "severity": "warning",
            })

    # Missing env vars — only publishing-critical
    for m in health.get("missing_env", []):
        if m["service"] in ("wix", "instagram", "facebook", "threads", "openai"):
            items.append({
                "emoji":    "🔴",
                "title":    f"Missing secrets for {m['service']}",
                "reason":   m["message"],
                "action":   m["action"],
                "severity": "critical",
            })

    # Failed topics
    for t in classified.get("failed", []):
        items.append({
            "emoji":    "❌",
            "title":    f"Publishing failed: \"{t['title']}\"",
            "reason":   t.get("failure_stage", "unknown stage"),
            "action":   (
                f"Open GitHub Actions → find run that processed topic ID {t.get('id', '?')} "
                f"→ check step logs. Error: {t.get('failure_error', '')[:120]}"
            ),
            "severity": "critical",
        })

    # Partial topics
    for t in classified.get("partial", []):
        items.append({
            "emoji":    "⚠️",
            "title":    f"Partial publish: \"{t['title']}\"",
            "reason":   t.get("failure_stage", "some channels succeeded, some didn't"),
            "action":   (
                f"Check which channels need retry. "
                f"Error: {t.get('failure_error', 'see GitHub Actions logs')[:120]}"
            ),
            "severity": "warning",
        })

    return items


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------

def build_report() -> dict:
    inventory  = load_inventory(TOPICS_FILE)
    health     = run_health_check(TOPICS_FILE)
    topics     = _collect_topics()
    classified = _classify_topics(topics)
    dq         = _data_quality(health)
    schedule   = _today_schedule()
    owner_sum  = _owner_summary(health, inventory, classified)
    actions    = _actionable_items(health, classified)

    return {
        "report_type":    "daily",
        "report_date":    TODAY.isoformat(),
        "generated_at":   datetime.now(tz=timezone.utc).isoformat(),
        "today_schedule": schedule,
        "owner_summary":  owner_sum,
        "topic_inventory": inventory,
        "pipeline_health": {
            "overall_status":    health["overall_status"],
            "critical_reasons":  health.get("critical_reasons", []),
            "action_items":      health.get("action_items", []),
            "channels":          health["channels"],
            "token_issues":      health["token_issues"],
            "missing_env":       health["missing_env"],
            "permissions_audit": health.get("permissions_audit", []),
        },
        "cycle_summary": {
            "complete":  len(classified["complete"]),
            "partial":   len(classified["partial"]),
            "failed":    len(classified["failed"]),
            "pending":   len(classified["pending"]),
            "total":     len(topics),
        },
        "classified_topics": classified,
        "actionable_items":  actions,
        "data_quality":      dq,
        # Keep full topic list for JSON artifact
        "topics": topics,
    }


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def _icon(status: str) -> str:
    return _STATUS_ICON.get(status.lower(), "⚪")


def to_markdown(report: dict) -> str:
    d          = report["report_date"]
    health     = report["pipeline_health"]
    inv        = report["topic_inventory"]
    dq         = report["data_quality"]
    cycle      = report["cycle_summary"]
    actions    = report["actionable_items"]
    classified = report["classified_topics"]
    perms      = health.get("permissions_audit", [])
    schedule   = report["today_schedule"]
    owner_sum  = report["owner_summary"]

    overall_icon = _icon(health["overall_status"])
    inv_icon     = _icon(inv["status"])
    dq_icon      = "🟢" if dq["total"] >= 70 else ("🟡" if dq["total"] >= 40 else "🔴")
    action_icon  = "🔴" if actions else "🟢"

    schedule_note = {
        "content": "Content day (Mon/Wed/Fri) — Main pipeline scheduled",
        "stories": "Stories day (Tue/Thu/Sat) — Instagram Stories scheduled",
        "none":    "Sunday — No publishing scheduled",
    }.get(schedule, "")

    lines = [
        f"# 🎯 Clarity Lab — Daily Report {d}",
        f"_{schedule_note}_",
        "",
    ]

    # ── Owner Summary ──────────────────────────────────────────────────────
    lines += ["## Owner Summary", ""]
    lines.append(owner_sum)
    lines.append("")

    # ── At a Glance (cockpit) ──────────────────────────────────────────────
    lines += ["## At a Glance", ""]
    lines.append(f"{overall_icon} **Publishing:** {health['overall_status'].upper()}")
    lines.append(f"{inv_icon} **Topic Inventory:** {inv['status'].upper()} ({inv['remaining_topics']} topics remaining)")
    lines.append(f"{dq_icon} **Data Quality:** {dq['total']}/100 — {dq['confidence']}")
    lines.append(f"{action_icon} **Action Required:** {'YES (' + str(len(actions)) + ' item' + ('s' if len(actions) != 1 else '') + ')' if actions else 'NO'}")
    lines.append("")
    lines.append("**This cycle:**")
    lines.append(f"✅ {cycle['complete']} complete  ")
    if cycle["partial"]:
        lines.append(f"🟡 {cycle['partial']} partial  ")
    if cycle["failed"]:
        lines.append(f"❌ {cycle['failed']} failed  ")
    if cycle["pending"]:
        lines.append(f"⏳ {cycle['pending']} pending  ")
    lines.append("")

    # ── Channel Status (quick view) ────────────────────────────────────────
    lines += ["## Channel Status", ""]
    for ch_info in health["channels"]:
        ch = ch_info["channel"]
        ch_icon = _icon(ch_info["status"])
        pub = ch_info["published"]

        if ch == "Threads":
            lines.append(f"{ch_icon} **Threads** — via separate workflow (threads_workflow.yml)")
        elif ch == "Instagram" and schedule == "stories":
            lines.append(f"{ch_icon} **Instagram** — {pub} published · Stories pipeline runs today")
        else:
            lines.append(f"{ch_icon} **{ch}** — {pub} published")

        perm = next((p for p in perms if p["channel"] == ch), None)
        if perm and perm["metrics"] not in ("available",):
            met = perm["metrics"]
            met_icon = "🟡" if met == "partial" else "⚪"
            lines.append(f"  {met_icon} Metrics: {met}")
    lines.append("")

    # Stories note
    lines.append("**📸 Instagram Stories**")
    if schedule == "stories":
        lines.append("Stories pipeline runs today (Tue/Thu/Sat at 9:00 UTC).")
    else:
        lines.append("Runs Tue/Thu/Sat at 9:00 UTC.")
    lines.append("⚪ Outcome not tracked in topics.csv — check GitHub Actions logs for stories_workflow.yml.")
    lines.append("")

    # ── Action Required ────────────────────────────────────────────────────
    if actions:
        lines += ["## 🔴 Action Required", ""]
        for item in actions:
            lines.append(f"### {item['emoji']} {item['title']}")
            lines.append(f"**Why:** {item['reason']}")
            lines.append(f"**What to do:** {item['action']}")
            lines.append("")
    else:
        lines += ["## ✅ Action Required", ""]
        lines.append("No action required today. Pipeline is operating normally.")
        lines.append("")

    # ── Partial Topic Diagnostics ──────────────────────────────────────────
    if classified["partial"] or classified["failed"]:
        lines += ["## Topic Issues", ""]
        for t in classified["partial"]:
            lines.append(f"### 🟡 Partial: \"{t['title']}\"")
            lines.append(f"- **Stage:** {t.get('failure_stage', 'unknown')}")
            lines.append(f"- **Error:** {t.get('failure_error', 'No error recorded.')}")
            lines.append("")
        for t in classified["failed"]:
            lines.append(f"### ❌ Failed: \"{t['title']}\"")
            lines.append(f"- **Stage:** {t.get('failure_stage', 'unknown')}")
            lines.append(f"- **Error:** {t.get('failure_error', 'No error recorded.')}")
            lines.append("")

    # ── Why This Matters ───────────────────────────────────────────────────
    why_items: list[dict] = []
    for p in perms:
        if p["channel"] == "Instagram" and p["metrics"] != "available":
            why_items.append({"section": "Instagram Insights", **_WHY_IT_MATTERS["instagram_metrics"]})
        if p["channel"] == "Facebook" and p["metrics"] not in ("available",):
            why_items.append({"section": "Facebook Reach", **_WHY_IT_MATTERS["facebook_metrics"]})
        if p["channel"] == "Threads" and p["metrics"] != "available":
            why_items.append({"section": "Threads Insights", **_WHY_IT_MATTERS["threads_metrics"]})
        if p["channel"] == "Wix" and p["metrics"] != "available":
            why_items.append({"section": "Wix Analytics", **_WHY_IT_MATTERS["wix_analytics"]})

    if why_items:
        lines += ["## Why This Matters", ""]
        for w in why_items:
            can_fix = w.get("can_fix_today", "Unknown")
            fix_icon = "✅" if str(can_fix).startswith("Yes") else "🔴"
            lines.append(f"**{w['section']}**")
            lines.append(f"- Impact: {w['impact']}")
            lines.append(f"- Priority: {w.get('priority', 'Unknown')}")
            lines.append(f"- Can owner fix today: {fix_icon} {can_fix}")
            lines.append(f"- Action: {w.get('action', 'n/a')}")
            lines.append("")

    # ── Topic Inventory ────────────────────────────────────────────────────
    lines += ["## Topic Inventory", ""]
    lines.append(f"- Remaining: {inv['remaining_topics']} topics")
    lines.append(f"- Publishing cadence: {inv.get('cadence_per_week', 3)} topics/week ({inv.get('cadence_source', 'default')})")
    lines.append(f"- Estimated runway: ~{inv['days_left']} days")
    lines.append(f"- Status: **{inv['status'].upper()}** — {inv['message']}")
    lines.append("")

    # ── Data Quality ───────────────────────────────────────────────────────
    lines += [f"## Data Quality Score: {dq['total']}/100", ""]
    lines.append("_Score is calculated from a transparent formula — each category has a defined maximum._")
    lines.append("")
    lines.append("| Category | Score | Max | Status |")
    lines.append("|---|---|---|---|")
    for b in dq["breakdown"]:
        st = "✅" if b["available"] else "⚪"
        lines.append(f"| {b['label']} | {b['score']} | {b['max']} | {st} |")
    lines.append(f"| **Total** | **{dq['total']}** | **100** | |")
    lines.append("")
    lines.append(f"**Confidence: {dq['confidence']}**")
    lines.append("")

    # ── Business Impact ────────────────────────────────────────────────────
    lines += ["## Business Impact", ""]
    lines.append("_This section will populate when engagement and reach data become available._")
    lines.append("")
    lines.append("| Metric | Status |")
    lines.append("|---|---|")
    lines.append("| Instagram followers | ⚪ Not tracked |")
    lines.append("| Facebook page reach | ⚪ Not tracked |")
    lines.append("| Threads followers | ⚪ Not tracked |")
    lines.append("| Wix article views | ⚪ Not tracked (check dashboard) |")
    lines.append("| Email subscribers | ⚪ Not tracked |")
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
    print(f"Schedule       : {result['today_schedule']}")
    print(f"Pipeline status: {result['pipeline_health']['overall_status']}")
    print(f"Cycle summary  : {result['cycle_summary']}")
    print(f"Data quality   : {result['data_quality']['total']}/100 ({result['data_quality']['confidence']})")
    print(f"Owner summary  : {result['owner_summary'][:100]}...")
