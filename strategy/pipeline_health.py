"""
Pipeline Health Monitor for Clarity Lab Pipeline.

Inspects topics.csv, environment variables, and token expiry to produce
a structured health report. Never blocks the publishing pipeline — all
errors are returned as data, not raised as exceptions.

Health statuses: healthy | warning | critical | blocked
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

# How many days without a publish before we escalate
WARN_DAYS_NO_PUBLISH  = 3
CRIT_DAYS_NO_PUBLISH  = 7

# Token expiry thresholds
TOKEN_WARN_DAYS  = 14
TOKEN_CRIT_DAYS  = 3

REQUIRED_ENV_VARS = {
    "wix":       ["WIX_SITE_ID", "WIX_API_KEY"],
    "instagram": ["IG_USER_ID", "IG_TOKEN"],
    "facebook":  ["FB_PAGE_ID", "FB_PAGE_TOKEN"],
    "threads":   ["THREADS_USER_ID", "THREADS_ACCESS_TOKEN"],
    "openai":    ["OPENAI_API_KEY"],
    "cloudinary":["CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET"],
    "email":     ["GMAIL_SENDER", "GMAIL_APP_PASSWORD", "REPORT_EMAIL_TO"],
}

# Optional ISO-date env vars that declare token expiry
TOKEN_EXPIRY_VARS = {
    "instagram": "IG_TOKEN_EXPIRES_AT",
    "threads":   "THREADS_TOKEN_EXPIRES_AT",
}


def _check_env_vars() -> dict[str, list[str]]:
    """Return {service: [missing_var, ...]} for each service with gaps."""
    missing: dict[str, list[str]] = {}
    for service, vars_ in REQUIRED_ENV_VARS.items():
        absent = [v for v in vars_ if not os.environ.get(v)]
        if absent:
            missing[service] = absent
    return missing


def _check_token_expiry() -> list[dict]:
    """Return list of expiry issues for tokens that declare an expiry date."""
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
    Returns {channel: {published, failed, partial, last_published_at}}
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


def _days_since(date_str: Optional[str]) -> Optional[int]:
    if not date_str:
        return None
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return (datetime.now(tz=timezone.utc) - dt).days
    except ValueError:
        return None


def run_health_check(topics_file: Optional[Path] = None) -> dict:
    """
    Run all health checks and return a structured report.
    Never raises.
    """
    path = topics_file or Path(os.environ.get("TOPICS_FILE", str(DEFAULT_TOPICS_FILE)))

    missing_env  = _check_env_vars()
    token_issues = _check_token_expiry()
    channel_stats = _channel_stats(path)

    channel_health: list[dict] = []
    for ch, s in channel_stats.items():
        days_since = _days_since(s["last_published_at"])
        if days_since is None:
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
            "last_published_at": s["last_published_at"],
            "days_since_last_publish": days_since,
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

    return {
        "overall_status": overall,
        "checked_at": datetime.now(tz=timezone.utc).isoformat(),
        "channels": channel_health,
        "token_issues": token_issues,
        "missing_env": missing_env_issues,
        "action_required": overall in ("blocked", "critical", "warning"),
    }


def format_summary(report: dict) -> str:
    lines = [
        "=== Clarity Lab — Pipeline Health ===",
        f"Status   : {report['overall_status'].upper()}",
        f"Checked  : {report['checked_at']}",
        "",
        "--- Channels ---",
    ]
    for ch in report["channels"]:
        lines.append(f"  {ch['channel']:12s}: {ch['status'].upper():8s} — {ch['message']}")

    if report["token_issues"]:
        lines.append("")
        lines.append("--- Token Issues ---")
        for t in report["token_issues"]:
            lines.append(f"  {t['platform']:12s}: {t['message']}")
            lines.append(f"               Action: {t['action']}")

    if report["missing_env"]:
        lines.append("")
        lines.append("--- Missing Environment Variables ---")
        for m in report["missing_env"]:
            lines.append(f"  {m['service']:12s}: {m['message']}")
            lines.append(f"               Action: {m['action']}")

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
