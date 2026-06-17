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
        for key in ("report_type", "report_date", "topic_inventory", "pipeline_health",
                    "today_activity", "data_quality"):
            assert key in report, f"Missing key: {key}"

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

    def test_data_quality_has_required_keys(self, tmp_path):
        path = _make_topics([])
        with mock.patch.object(dr, "TOPICS_FILE", path):
            report = dr.build_report()
        dqa = report["data_quality"]
        assert "score" in dqa
        assert "available" in dqa
        assert "missing" in dqa
        assert "confidence" in dqa
        assert dqa["confidence"] in ("Low", "Medium", "High")

    def test_failed_topics_have_stage_and_error(self, tmp_path):
        path = _make_topics([{
            "ID": "1", "Topic / Working Title": "Test Topic",
            "Pipeline State": "partial_failure",
            "Wix Status": "partial_failure",
            "Instagram Status": "published",
            "Facebook Status": "",
        }])
        with mock.patch.object(dr, "TOPICS_FILE", path):
            report = dr.build_report()
        assert len(report["failed_topics"]) >= 1
        t = report["failed_topics"][0]
        assert "failure_stage" in t
        assert "failure_error" in t
        assert "Instagram" in t["failure_stage"]  # succeeded
        assert "Wix" in t["failure_stage"]        # failed

    def test_failed_topic_no_error_says_where_to_look(self, tmp_path):
        path = _make_topics([{
            "ID": "3", "Topic / Working Title": "The pattern you keep returning to",
            "Pipeline State": "partial_failure",
            "Wix Status": "partial_failure",
            "Instagram Status": "published",
        }])
        with mock.patch.object(dr, "TOPICS_FILE", path):
            report = dr.build_report()
        t = report["failed_topics"][0]
        # When no error recorded, must tell user where to find it
        assert "GitHub Actions" in t["failure_error"] or len(t["failure_error"]) > 0


class TestInferFailureStage:
    def test_infer_all_failed(self):
        topic = {
            "wix_status": "failed",
            "instagram_status": "failed",
            "facebook_status": "failed",
            "threads_status": "",
            "errors": "",
        }
        stage, error = dr._infer_failure_stage(topic)
        assert "Wix" in stage
        assert "Instagram" in stage
        assert "GitHub Actions" in error  # no error recorded

    def test_infer_partial_success(self):
        topic = {
            "wix_status": "published",
            "instagram_status": "published",
            "facebook_status": "",
            "threads_status": "",
            "errors": "",
        }
        stage, error = dr._infer_failure_stage(topic)
        assert "Succeeded" in stage
        assert "Instagram" in stage or "Wix" in stage

    def test_infer_error_message_preserved(self):
        topic = {
            "wix_status": "failed",
            "instagram_status": "",
            "facebook_status": "",
            "threads_status": "",
            "errors": "HTTP 403 Unauthorized",
        }
        stage, error = dr._infer_failure_stage(topic)
        assert "HTTP 403" in error


class TestToMarkdownV3:
    def _get_report(self, path):
        with mock.patch.object(dr, "TOPICS_FILE", path):
            return dr.build_report()

    def test_at_a_glance_section_present(self, tmp_path):
        path = _make_topics([])
        report = self._get_report(path)
        md = dr.to_markdown(report)
        assert "## At a Glance" in md

    def test_action_required_section_always_present(self, tmp_path):
        path = _make_topics([])
        report = self._get_report(path)
        md = dr.to_markdown(report)
        assert "Action Required" in md

    def test_action_required_no_action_text_when_clean(self, tmp_path):
        path = _make_topics([])
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
        assert "No manual action required today." in md

    def test_critical_reasons_shown_when_critical(self, tmp_path):
        path = _make_topics([])
        health = {
            "overall_status": "critical",
            "critical_reasons": ["No Wix publish. 0 successful, 1 failure.", "Missing IG_TOKEN"],
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
        assert "Critical" in md
        assert "No Wix publish" in md

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
        assert "Critical Reasons" not in md

    def test_data_quality_section_present(self, tmp_path):
        path = _make_topics([])
        report = self._get_report(path)
        md = dr.to_markdown(report)
        assert "Data Quality" in md
        assert "/100" in md

    def test_permissions_section_present(self, tmp_path):
        path = _make_topics([])
        with mock.patch.object(dr, "TOPICS_FILE", path):
            report = dr.build_report()
        md = dr.to_markdown(report)
        assert "Permissions & Data Availability" in md

    def test_days_left_explanation_present(self, tmp_path):
        path = _make_topics([])
        report = self._get_report(path)
        md = dr.to_markdown(report)
        assert "cadence" in md.lower() or "Estimated runway" in md

    def test_recommended_next_actions_present(self, tmp_path):
        path = _make_topics([])
        report = self._get_report(path)
        md = dr.to_markdown(report)
        assert "Recommended Next Actions" in md

    def test_all_channels_present(self, tmp_path):
        path = _make_topics([])
        report = self._get_report(path)
        md = dr.to_markdown(report)
        for ch in ["Wix", "Instagram", "Facebook", "Threads"]:
            assert ch in md

    def test_failed_topic_diagnostics_in_markdown(self, tmp_path):
        path = _make_topics([{
            "ID": "3", "Topic / Working Title": "The pattern you keep returning to",
            "Pipeline State": "partial_failure",
            "Wix Status": "partial_failure",
            "Instagram Status": "published",
        }])
        with mock.patch.object(dr, "TOPICS_FILE", path):
            report = dr.build_report()
        md = dr.to_markdown(report)
        assert "Failed Topic Diagnostics" in md
        assert "The pattern you keep returning to" in md

    def test_visual_status_indicators_present(self, tmp_path):
        path = _make_topics([])
        report = self._get_report(path)
        md = dr.to_markdown(report)
        # At least some visual indicators must be present
        has_indicator = any(icon in md for icon in ("🟢", "🟡", "🔴", "✅", "⚪", "⚠️"))
        assert has_indicator


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
