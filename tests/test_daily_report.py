"""Tests for reports/daily_report.py"""

import csv
import json
import os
import tempfile
from datetime import date
from pathlib import Path
from unittest import mock

import pytest

import reports.daily_report as dr


def _make_topics(rows: list[dict]) -> Path:
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="")
    fieldnames = [
        "ID", "Date Added", "Topic / Working Title", "Status", "Pipeline State",
        "Wix Status", "Instagram Status", "Facebook Status", "Threads Status",
        "Published URL", "Website Published URL", "Instagram Published URL",
        "Publish Status Code", "Publication Errors", "Last Error", "Retry Available",
    ]
    writer = csv.DictWriter(tmp, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow({f: row.get(f, "") for f in fieldnames})
    tmp.close()
    return Path(tmp.name)


class TestBuildReport:
    def test_report_has_required_keys(self, tmp_path):
        path = _make_topics([])
        with mock.patch.object(dr, "TOPICS_FILE", path):
            report = dr.build_report()
        assert "report_type" in report
        assert "report_date" in report
        assert "topic_inventory" in report
        assert "pipeline_health" in report
        assert "today_activity" in report

    def test_pipeline_health_has_critical_reasons(self, tmp_path):
        path = _make_topics([])
        with mock.patch.object(dr, "TOPICS_FILE", path):
            report = dr.build_report()
        assert "critical_reasons" in report["pipeline_health"]

    def test_pipeline_health_has_permissions_audit(self, tmp_path):
        path = _make_topics([])
        with mock.patch.object(dr, "TOPICS_FILE", path):
            report = dr.build_report()
        assert "permissions_audit" in report["pipeline_health"]
        assert len(report["pipeline_health"]["permissions_audit"]) == 4

    def test_report_type_is_daily(self, tmp_path):
        path = _make_topics([])
        with mock.patch.object(dr, "TOPICS_FILE", path):
            report = dr.build_report()
        assert report["report_type"] == "daily"

    def test_failed_topics_counted(self, tmp_path):
        path = _make_topics([
            {"ID": "1", "Pipeline State": "partial_failure", "Wix Status": "failed"},
            {"ID": "2", "Pipeline State": "completed", "Wix Status": "published"},
        ])
        with mock.patch.object(dr, "TOPICS_FILE", path):
            report = dr.build_report()
        assert report["today_activity"]["failed_topics"] >= 1


class TestToMarkdownV2:
    def _get_report(self, topics_path):
        with mock.patch.object(dr, "TOPICS_FILE", topics_path):
            return dr.build_report()

    def test_action_required_section_always_present(self, tmp_path):
        path = _make_topics([])
        report = self._get_report(path)
        md = dr.to_markdown(report)
        assert "## Action Required" in md

    def test_action_required_no_action_text_when_clean(self, tmp_path):
        """If no issues, section says no action required."""
        path = _make_topics([])
        # Patch health to return clean state
        clean_health = {
            "overall_status": "healthy",
            "critical_reasons": [],
            "action_items": [],
            "channels": [],
            "token_issues": [],
            "missing_env": [],
            "permissions_audit": [],
        }
        with mock.patch.object(dr, "TOPICS_FILE", path), \
             mock.patch("reports.daily_report.run_health_check", return_value=clean_health):
            report = dr.build_report()
        md = dr.to_markdown(report)
        assert "No manual action required today" in md

    def test_critical_reasons_shown_when_critical(self, tmp_path):
        path = _make_topics([])
        health = {
            "overall_status": "critical",
            "critical_reasons": ["No Wix publish in 10 days.", "Missing IG_TOKEN"],
            "action_items": ["Fix Wix token"],
            "channels": [],
            "token_issues": [],
            "missing_env": [],
            "permissions_audit": [],
        }
        with mock.patch.object(dr, "TOPICS_FILE", path), \
             mock.patch("reports.daily_report.run_health_check", return_value=health):
            report = dr.build_report()
        md = dr.to_markdown(report)
        assert "## Critical Reasons" in md
        assert "No Wix publish in 10 days." in md

    def test_critical_section_not_shown_when_healthy(self, tmp_path):
        path = _make_topics([])
        health = {
            "overall_status": "healthy",
            "critical_reasons": [],
            "action_items": [],
            "channels": [],
            "token_issues": [],
            "missing_env": [],
            "permissions_audit": [],
        }
        with mock.patch.object(dr, "TOPICS_FILE", path), \
             mock.patch("reports.daily_report.run_health_check", return_value=health):
            report = dr.build_report()
        md = dr.to_markdown(report)
        assert "## Critical Reasons" not in md

    def test_permissions_table_present(self, tmp_path):
        path = _make_topics([])
        with mock.patch.object(dr, "TOPICS_FILE", path):
            report = dr.build_report()
        md = dr.to_markdown(report)
        assert "## Permissions & Data Availability" in md

    def test_days_left_explanation_present(self, tmp_path):
        path = _make_topics([])
        with mock.patch.object(dr, "TOPICS_FILE", path):
            report = dr.build_report()
        md = dr.to_markdown(report)
        assert "cadence" in md.lower() or "Estimated runway" in md

    def test_recommended_next_actions_present(self, tmp_path):
        path = _make_topics([])
        with mock.patch.object(dr, "TOPICS_FILE", path):
            report = dr.build_report()
        md = dr.to_markdown(report)
        assert "## Recommended Next Actions" in md

    def test_markdown_contains_channel_breakdown(self, tmp_path):
        path = _make_topics([])
        with mock.patch.object(dr, "TOPICS_FILE", path):
            report = dr.build_report()
        md = dr.to_markdown(report)
        for ch in ["Wix", "Instagram", "Facebook", "Threads"]:
            assert ch in md


class TestSaveReport:
    def test_saves_json_and_md(self, tmp_path):
        path = _make_topics([])
        with mock.patch.object(dr, "TOPICS_FILE", path), \
             mock.patch.object(dr, "REPORTS_DIR", tmp_path):
            report = dr.build_report()
            md = dr.to_markdown(report)
            json_path, md_path = dr.save_report(report, md)
        assert json_path.exists()
        assert md_path.exists()
        data = json.loads(json_path.read_text())
        assert data["report_type"] == "daily"

    def test_run_does_not_raise_on_email_fail(self, tmp_path):
        path = _make_topics([])
        with mock.patch.object(dr, "TOPICS_FILE", path), \
             mock.patch.object(dr, "REPORTS_DIR", tmp_path), \
             mock.patch("reports.daily_report.send_daily_report", return_value=False):
            result = dr.run(send_email=True)
        assert result["report_type"] == "daily"
