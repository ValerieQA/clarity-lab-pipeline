"""
Pipeline Health Monitor for Clarity Lab Pipeline.

Inspects topics.csv, environment variables, and token expiry to produce
a structured health report. Never blocks the publishing pipeline — all
errors are returned as data, not raised as exceptions.

Health statuses: healthy | warning | critical | blocked

Key design rule: every non-healthy status MUST have an explicit reason
in the critical_reasons list. Reports must never show CRITICAL without
explaining why.
"""

from __future__ import annotations

import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DEFAULT_TOPICS_FILE = Path(__file__).resolve().parents[1] / "topics.csv"

WARN_DAYS_NO_PUBLISH = 3
CRIT_DAYS_NO_PUBLISH = 7

TOKEN_WARN_DAYS = 14
TOKEN_CRIT_DAYS = 3

# Publishing secrets required for each channel
REQUIRED_ENV_VARS = {
    "wix":        ["WIX_SITE_ID", "WIX_API_KEY"],
    "instagram":  ["IG_USER_ID", "IG_TOKEN"],
    "facebook":   ["FB_PAGE_ID", "FB_PAGE_TOKEN"],
    "threads":    ["THREADS_USER_ID", "THREADS_ACCESS_TOKEN"],
    "openai":     ["OPENAI_API_KEY"],
    "cloudinary": ["CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET"],
    "email":      ["GMAIL_SENDER", "GMAIL_APP_PASSWORD", "REPORT_EMAIL_TO"],
}

TOKEN_EXPIRY_VARS = {
    "instagram": "IG_TOKEN_EXPIRES_AT",
    "threads":   "THREADS_TOKEN_EXPIRES_AT",
}

# Known permissions audit per channel.
# These describe what IS and ISN'T available at the API level,
# independent of whether secrets are set.
CHANNEL_PERMISSIONS_AUDIT = {
    "Wix": {
        "publishing":  ("available", "WIX_API_KEY + WIX_SITE_ID"),
        "metrics":     ("unavailable", "Wix Blog REST API does not expose per-post analytics. Check Wix dashboard manually."),
        "comments":    ("n/a", "Not collected via API."),
    },
    "Instagram": {
        "publishing":  ("available", "Requires IG_TOKEN + IG_USER_ID"),
        "metrics":     ("unavailable", "Requires permission: instagram_manage_insights (not currently granted). Submit for Meta App Review to enable."),
        "comments":    ("unavailable", "Requires permission: instagram_manage_comments (not currently granted)."),
    },
    "Facebook": {
        "publishing":  ("available", "Requires FB_PAGE_TOKEN + FB_PAGE_ID"),
        "metrics":     ("partial", "Basic reactions available via Graph API. Reach/impressions require pages_read_engagement permission (not confirmed granted)."),
        "comments":    ("partial", "Basic comment count available. Full comment text requires pages_read_engagement."),
    },
    "Threads": {
        "publishing":  ("available", "Managed by threads_workflow.yml separately from main pipeline. Not tracked in topics.csv Threads Status column."),
        "metrics":     ("unavailable", "Requires permission: threads_manage_insights (not currently granted)."),
        "comments":    ("available", "Collected by threads_workflow.yml into data/threads_comments.csv."),
    },
}


def _check_env_vars() -> dict[str, list[str]]:
    missing: dict[str, list[str]] = {}
    for service, vars_ in REQUIRED_ENV_VARS.items():
        absent = [v for v in vars_ if not os.environ.get(v)]
        if absent:
            missing[service] = absent
    return missing


def _check_token_expiry() -> list[dict]:
    issues = []
    now = datetime.now(tz=timezone.utc)
    for platform, env_var in TOKEN_EXPIRY_VARS.items():
        raw = os.environ.get(env_var, "")
        if not raw:
            continue
        try:
            expires = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            days_left = (expires - now).days
            if days_left < 0:
                issues.append({
                    "platform": platform,
                    "status": "blocked",
                    "days_left": days_left,
                    "message": f"{platform.capitalize()} token EXPIRED {abs(days_left)} day(s) ago.",
                    "action": f"Regenerate {platform} token and update secret {env_var}.",
                })
            elif days_left <= TOKEN_CRIT_DAYS:
                issues.append({
                    "platform": platform,
                    "status": "critical",
                    "days_left": days_left,
                    "message": f"{platform.capitalize()} token expires in {days_left} day(s).",
                    "action": f"Refresh {platform} token immediately. Update secret {env_var}.",
                })
            elif days_left <= TOKEN_WARN_DAYS:
                issues.append({
                    "platform": platform,
                    "status": "warning",
                    "days_left": days_left,
                    "message": f"{platform.capitalize()} token expires in {days_left} day(s).",
                    "action": f"Plan {platform} token refresh. Update secret {env_var}.",
                })
        except ValueError:
            issues.append({
                "platform": platform,
                "status": "warning",
                "days_left": None,
                "message": f"Cannot parse {env_var}='{raw}'. Expected ISO-8601 date.",
                "action": "Fix the date format in the secret.",
            })
    return issues


def _channel_stats(topics_file: Path) -> dict[str, dict]:
    """
    Read topics.csv and aggregate per-channel publish stats.

    Note: Threads Status in topics.csv is typically empty or 'skipped' because
    Threads publishing is managed by threads_workflow.yml independently.
    Threads publish history lives in data/threads_posts.csv, not topics.csv.
    This is expected behaviour, not a bug.
    """
    channels = ["Wix", "Instagram", "Facebook", "Threads"]
    stats: dict[str, dict] = {
        ch: {"published": 0, "failed": 0, "partial": 0, "last_published_at": None}
        for ch in channels
    }

    if not topics_file.exists():
        return stats

    with topics_file.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            date_added = row.get("Date Added", "").strip()
            for ch in channels:
                col = f"{ch} Status"
                val = row.get(col, "").strip().lower()
                if val == "published":
                    stats[ch]["published"] += 1
                    if date_added and (
                        stats[ch]["last_published_at"] is None
                        or date_added > stats[ch]["last_published_at"]
                    ):
                        stats[ch]["last_published_at"] = date_added
                elif val in {"failed", "error"}:
                    stats[ch]["failed"] += 1
                elif val in {"partial_failure", "partial failure"}:
                    stats[ch]["partial"] += 1

    return stats


def _threads_last_publish() -> Optional[str]:
    """Check data/threads_posts.csv for last Threads publish date."""
    posts_file = Path("data/threads_posts.csv")
    if not posts_file.exists():
        return None
    last_date: Optional[str] = None
    try:
        with posts_file.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                dt = (row.get("published_at") or row.get("created_at") or "").strip()[:10]
                if dt and (last_date is None or dt > last_date):
                    last_date = dt
    except Exception:
        pass
    return last_date


def _days_since(date_str: Optional[str]) -> Optional[int]:
    if not date_str:
        return None
    try:
        dt = datetime.strptime(date_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return (datetime.now(tz=timezone.utc) - dt).days
    except ValueError:
        return None


def run_health_check(topics_file: Optional[Path] = None) -> dict:
    """
    Run all health checks. Returns structured report with explicit
    critical_reasons list so reports can always explain status.
    Never raises.
    """
    path = topics_file or Path(os.environ.get("TOPICS_FILE", str(DEFAULT_TOPICS_FILE)))

    missing_env   = _check_env_vars()
    token_issues  = _check_token_expiry()
    channel_stats = _channel_stats(path)

    # Override Threads last_published_at from threads_posts.csv
    threads_last = _threads_last_publish()
    if threads_last and channel_stats["Threads"]["last_published_at"] is None:
        channel_stats["Threads"]["last_published_at"] = threads_last
        # Mark as separate-workflow channel
        channel_stats["Threads"]["via_separate_workflow"] = True

    channel_health: list[dict] = []
    for ch, s in channel_stats.items():
        days_since = _days_since(s.get("last_published_at"))
        via_separate = s.get("via_separate_workflow", False)

        if ch == "Threads" and via_separate and days_since is not None:
            # Threads is healthy if it's been publishing via its own workflow
            if days_since >= CRIT_DAYS_NO_PUBLISH:
                ch_status = "warning"
                ch_msg = f"Last Threads publish {days_since} day(s) ago (via threads_workflow.yml)."
            else:
                ch_status = "healthy"
                ch_msg = f"Last Threads publish {days_since} day(s) ago (via threads_workflow.yml)."
        elif days_since is None:
            ch_status = "unknown"
            ch_msg = f"No successful {ch} publish recorded."
        elif days_since >= CRIT_DAYS_NO_PUBLISH:
            ch_status = "critical"
            ch_msg = f"No {ch} publish in {days_since} day(s)."
        elif days_since >= WARN_DAYS_NO_PUBLISH:
            ch_status = "warning"
            ch_msg = f"No {ch} publish in {days_since} day(s)."
        else:
            ch_status = "healthy"
            ch_msg = f"Last {ch} publish {days_since} day(s) ago."

        channel_health.append({
            "channel": ch,
            "status": ch_status,
            "published": s["published"],
            "failed": s["failed"],
            "partial": s["partial"],
            "last_published_at": s.get("last_published_at"),
            "days_since_last_publish": days_since,
            "via_separate_workflow": via_separate,
            "message": ch_msg,
        })

    # Aggregate overall status
    all_statuses: list[str] = (
        [t["status"] for t in token_issues]
        + [c["status"] for c in channel_health]
        + (["blocked"] if any(missing_env.values()) else [])
    )

    def _worst(statuses: list[str]) -> str:
        for level in ("blocked", "critical", "warning", "unknown"):
            if level in statuses:
                return level
        return "healthy"

    overall = _worst(all_statuses)

    # Build missing env summary
    missing_env_issues = [
        {
            "service": svc,
            "missing_vars": vars_,
            "status": "blocked",
            "message": f"Missing env vars for {svc}: {', '.join(vars_)}",
            "action": f"Add secrets to GitHub Actions: {', '.join(vars_)}",
        }
        for svc, vars_ in missing_env.items()
    ]

    # Build explicit critical_reasons — every non-healthy status must be explained
    critical_reasons: list[str] = []
    for t in token_issues:
        if t["status"] in ("blocked", "critical"):
            critical_reasons.append(t["message"] + f" Action: {t['action']}")
    for m in missing_env_issues:
        critical_reasons.append(m["message"])
    for ch in channel_health:
        if ch["status"] in ("critical",):
            critical_reasons.append(ch["message"])

    # Build action_items list — concrete next steps
    action_items: list[str] = []
    for t in token_issues:
        action_items.append(t["action"])
    for m in missing_env_issues:
        # Only surface publishing-critical services to avoid noise about metrics-only vars
        if m["service"] in ("wix", "instagram", "facebook", "threads", "openai"):
            action_items.append(m["action"])
    for ch in channel_health:
        if ch["status"] in ("critical", "blocked"):
            action_items.append(f"Investigate {ch['channel']} publishing — {ch['message']}")

    # Permissions audit — always included
    permissions_audit = []
    for ch_name, audit in CHANNEL_PERMISSIONS_AUDIT.items():
        permissions_audit.append({
            "channel": ch_name,
            "publishing": audit["publishing"][0],
            "publishing_note": audit["publishing"][1],
            "metrics": audit["metrics"][0],
            "metrics_note": audit["metrics"][1],
            "comments": audit["comments"][0],
            "comments_note": audit["comments"][1],
        })

    return {
        "overall_status": overall,
        "checked_at": datetime.now(tz=timezone.utc).isoformat(),
        "critical_reasons": critical_reasons,
        "action_items": action_items,
        "channels": channel_health,
        "token_issues": token_issues,
        "missing_env": missing_env_issues,
        "permissions_audit": permissions_audit,
        "action_required": overall in ("blocked", "critical", "warning"),
    }


def format_summary(report: dict) -> str:
    lines = [
        "=== Clarity Lab — Pipeline Health ===",
        f"Status   : {report['overall_status'].upper()}",
        f"Checked  : {report['checked_at']}",
    ]

    if report.get("critical_reasons"):
        lines += ["", "--- Critical Reasons ---"]
        for i, r in enumerate(report["critical_reasons"], 1):
            lines.append(f"  {i}. {r}")

    lines += ["", "--- Channels ---"]
    for ch in report["channels"]:
        lines.append(f"  {ch['channel']:12s}: {ch['status'].upper():8s} — {ch['message']}")

    if report["token_issues"]:
        lines += ["", "--- Token Issues ---"]
        for t in report["token_issues"]:
            lines.append(f"  {t['platform']:12s}: {t['message']}")
            lines.append(f"               Action: {t['action']}")

    if report["missing_env"]:
        lines += ["", "--- Missing Secrets ---"]
        for m in report["missing_env"]:
            lines.append(f"  {m['service']:12s}: {m['message']}")

    return "\n".join(lines)


if __name__ == "__main__":
    report = run_health_check()
    print(json.dumps(report, indent=2))
    print()
    print(format_summary(report))

    if report["action_required"] and os.environ.get("SEND_EMAIL_ALERTS", "").lower() == "true":
        from notifications.email_reporter import send_critical_alert
        send_critical_alert(format_summary(report))

    if report["overall_status"] in ("blocked", "critical"):
        sys.exit(2)
    elif report["overall_status"] == "warning":
        sys.exit(1)
    sys.exit(0)
