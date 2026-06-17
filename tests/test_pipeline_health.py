"""Tests for strategy/pipeline_health.py"""

import csv
import os
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import pytest

from strategy.pipeline_health import run_health_check, format_summary, _check_token_expiry


def _make_topics(rows: list[dict]) -> Path:
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="")
    fieldnames = ["ID", "Date Added", "Status", "Wix Status", "Instagram Status", "Facebook Status", "Threads Status"]
    writer = csv.DictWriter(tmp, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow({f: row.get(f, "") for f in fieldnames})
    tmp.close()
    return Path(tmp.name)


def _recent(days_ago: int = 1) -> str:
    return (date.today() - timedelta(days=days_ago)).isoformat()


class TestChannelStats:
    def test_healthy_when_any_published(self):
        """Channel is healthy if published_count > 0 — regardless of Date Added age."""
        rows = [{"Date Added": _recent(20), "Wix Status": "published",
                 "Instagram Status": "published", "Facebook Status": "published"}]
        path = _make_topics(rows)
        report = run_health_check(path)
        wix = next(c for c in report["channels"] if c["channel"] == "Wix")
        assert wix["status"] == "healthy"

    def test_no_false_critical_when_published_exists(self):
        """Bug: topics batch-added 15 days ago but published → must NOT be CRITICAL."""
        rows = [
            {"Date Added": _recent(15), "Wix Status": "published",
             "Instagram Status": "published", "Facebook Status": "published"},
            {"Date Added": _recent(14), "Wix Status": "published",
             "Instagram Status": "published", "Facebook Status": "published"},
        ]
        path = _make_topics(rows)
        with mock.patch("strategy.pipeline_health._threads_last_publish", return_value=_recent(2)):
            report = run_health_check(path)
        wix = next(c for c in report["channels"] if c["channel"] == "Wix")
        ig  = next(c for c in report["channels"] if c["channel"] == "Instagram")
        fb  = next(c for c in report["channels"] if c["channel"] == "Facebook")
        assert wix["status"] == "healthy", f"Wix was {wix['status']}: {wix['message']}"
        assert ig["status"]  == "healthy", f"Instagram was {ig['status']}: {ig['message']}"
        assert fb["status"]  == "healthy", f"Facebook was {fb['status']}: {fb['message']}"

    def test_critical_when_no_publish_ever(self):
        """Channel is critical if failed > 0 and published == 0."""
        rows = [{"Date Added": _recent(1), "Wix Status": "failed",
                 "Instagram Status": "failed", "Facebook Status": "failed"}]
        path = _make_topics(rows)
        with mock.patch("strategy.pipeline_health._threads_last_publish", return_value=None):
            report = run_health_check(path)
        wix = next(c for c in report["channels"] if c["channel"] == "Wix")
        assert wix["status"] == "critical"

    def test_unknown_when_no_data(self):
        rows = [{"Date Added": "", "Wix Status": "", "Instagram Status": "", "Facebook Status": "", "Threads Status": ""}]
        path = _make_topics(rows)
        with mock.patch("strategy.pipeline_health._threads_last_publish", return_value=None):
            report = run_health_check(path)
        wix = next(c for c in report["channels"] if c["channel"] == "Wix")
        assert wix["status"] == "unknown"

    def test_threads_uses_real_timestamp_not_date_added(self):
        """Threads health comes from threads_posts.csv, not Date Added."""
        rows = [{"Date Added": _recent(20)}]
        path = _make_topics(rows)
        with mock.patch("strategy.pipeline_health._threads_last_publish", return_value=_recent(2)):
            report = run_health_check(path)
        threads_ch = next(c for c in report["channels"] if c["channel"] == "Threads")
        assert threads_ch["status"] == "healthy"
        assert threads_ch["via_separate_workflow"] is True

    def test_no_publish_ever_is_unknown(self):
        rows = [{"Date Added": "", "Wix Status": "", "Instagram Status": "", "Facebook Status": "", "Threads Status": ""}]
        path = _make_topics(rows)
        with mock.patch("strategy.pipeline_health._threads_last_publish", return_value=None):
            report = run_health_check(path)
        threads_ch = next(c for c in report["channels"] if c["channel"] == "Threads")
        assert threads_ch["status"] == "unknown"

    def test_published_count_is_accurate(self):
        rows = [
            {"Wix Status": "published"},
            {"Wix Status": "published"},
            {"Wix Status": "failed"},
        ]
        path = _make_topics(rows)
        report = run_health_check(path)
        wix = next(c for c in report["channels"] if c["channel"] == "Wix")
        assert wix["published"] == 2
        assert wix["failed"] == 1


class TestCriticalReasons:
    def test_critical_status_always_has_reasons(self):
        path = _make_topics([{"Date Added": _recent(10), "Wix Status": "failed"}])
        with mock.patch("strategy.pipeline_health._threads_last_publish", return_value=None):
            report = run_health_check(path)
        if report["overall_status"] in ("critical", "blocked"):
            assert len(report["critical_reasons"]) > 0

    def test_healthy_has_no_critical_reasons(self):
        rows = [{"Date Added": _recent(1), "Wix Status": "published",
                 "Instagram Status": "published", "Facebook Status": "published"}]
        path = _make_topics(rows)
        env = {k: "x" for k in [
            "WIX_SITE_ID", "WIX_API_KEY", "IG_USER_ID", "IG_TOKEN",
            "FB_PAGE_ID", "FB_PAGE_TOKEN", "THREADS_USER_ID", "THREADS_ACCESS_TOKEN",
            "OPENAI_API_KEY", "CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY",
            "CLOUDINARY_API_SECRET", "GMAIL_SENDER", "GMAIL_APP_PASSWORD", "REPORT_EMAIL_TO",
        ]}
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch("strategy.pipeline_health._threads_last_publish", return_value=_recent(1)):
            report = run_health_check(path)
        if report["overall_status"] == "healthy":
            assert report["critical_reasons"] == []

    def test_missing_secrets_produce_reasons(self):
        path = _make_topics([])
        with mock.patch.dict(os.environ, {}, clear=True):
            report = run_health_check(path)
        assert len(report["critical_reasons"]) > 0


class TestPermissionsAudit:
    def test_permissions_audit_always_present(self):
        path = _make_topics([])
        report = run_health_check(path)
        assert "permissions_audit" in report
        assert len(report["permissions_audit"]) == 4

    def test_permissions_audit_has_required_fields(self):
        path = _make_topics([])
        report = run_health_check(path)
        for entry in report["permissions_audit"]:
            for field in ("channel", "publishing", "metrics", "comments", "metrics_note"):
                assert field in entry

    def test_permissions_audit_channels(self):
        path = _make_topics([])
        report = run_health_check(path)
        channels = {e["channel"] for e in report["permissions_audit"]}
        assert channels == {"Wix", "Instagram", "Facebook", "Threads"}


class TestActionItems:
    def test_action_items_present(self):
        path = _make_topics([])
        report = run_health_check(path)
        assert "action_items" in report

    def test_no_action_items_when_healthy(self):
        rows = [{"Date Added": _recent(1), "Wix Status": "published",
                 "Instagram Status": "published", "Facebook Status": "published"}]
        path = _make_topics(rows)
        env = {k: "x" for k in [
            "WIX_SITE_ID", "WIX_API_KEY", "IG_USER_ID", "IG_TOKEN",
            "FB_PAGE_ID", "FB_PAGE_TOKEN", "THREADS_USER_ID", "THREADS_ACCESS_TOKEN",
            "OPENAI_API_KEY", "CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY",
            "CLOUDINARY_API_SECRET", "GMAIL_SENDER", "GMAIL_APP_PASSWORD", "REPORT_EMAIL_TO",
        ]}
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch("strategy.pipeline_health._threads_last_publish", return_value=_recent(1)):
            report = run_health_check(path)
        if report["overall_status"] == "healthy":
            assert report["action_items"] == []


class TestMissingEnvVars:
    def test_missing_token_is_blocked(self):
        env = {k: v for k, v in os.environ.items()}
        env.pop("IG_TOKEN", None)
        env.pop("IG_USER_ID", None)
        path = _make_topics([])
        with mock.patch.dict(os.environ, env, clear=True):
            report = run_health_check(path)
        ig_missing = next((m for m in report["missing_env"] if m["service"] == "instagram"), None)
        assert ig_missing is not None
        assert ig_missing["status"] == "blocked"


class TestTokenExpiry:
    def test_expired_token(self):
        past = (date.today() - timedelta(days=5)).isoformat()
        with mock.patch.dict(os.environ, {"IG_TOKEN_EXPIRES_AT": past}):
            issues = _check_token_expiry()
        assert any(i["status"] == "blocked" for i in issues)

    def test_expiring_soon_warning(self):
        soon = (date.today() + timedelta(days=10)).isoformat()
        with mock.patch.dict(os.environ, {"IG_TOKEN_EXPIRES_AT": soon}):
            issues = _check_token_expiry()
        assert any(i["status"] == "warning" for i in issues)

    def test_healthy_token(self):
        future = (date.today() + timedelta(days=60)).isoformat()
        with mock.patch.dict(os.environ, {"IG_TOKEN_EXPIRES_AT": future}):
            issues = _check_token_expiry()
        assert len(issues) == 0


class TestFormatSummary:
    def test_summary_includes_status(self):
        path = _make_topics([])
        report = run_health_check(path)
        summary = format_summary(report)
        assert any(s in summary for s in ("HEALTHY", "UNKNOWN", "WARNING", "CRITICAL", "BLOCKED"))

    def test_summary_includes_critical_reasons_when_present(self):
        path = _make_topics([])
        with mock.patch.dict(os.environ, {}, clear=True):
            report = run_health_check(path)
        summary = format_summary(report)
        if report["critical_reasons"]:
            assert "Critical Reasons" in summary
