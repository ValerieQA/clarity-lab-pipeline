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
    def test_healthy_recent_publish(self):
        rows = [{"Date Added": _recent(1), "Wix Status": "published",
                 "Instagram Status": "published", "Facebook Status": "published", "Threads Status": "published"}]
        path = _make_topics(rows)
        report = run_health_check(path)
        wix = next(c for c in report["channels"] if c["channel"] == "Wix")
        assert wix["status"] == "healthy"

    def test_critical_no_publish_7_days(self):
        rows = [{"Date Added": _recent(8), "Wix Status": "published",
                 "Instagram Status": "", "Facebook Status": "", "Threads Status": ""}]
        path = _make_topics(rows)
        report = run_health_check(path)
        wix = next(c for c in report["channels"] if c["channel"] == "Wix")
        assert wix["status"] == "critical"

    def test_no_publish_ever_is_unknown(self):
        rows = [{"Date Added": "", "Wix Status": "", "Instagram Status": "", "Facebook Status": "", "Threads Status": ""}]
        path = _make_topics(rows)
        report = run_health_check(path)
        for ch in report["channels"]:
            assert ch["status"] == "unknown"


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
        assert "HEALTHY" in summary or "UNKNOWN" in summary or "WARNING" in summary or "CRITICAL" in summary or "BLOCKED" in summary
