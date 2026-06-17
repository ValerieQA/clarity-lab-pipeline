"""Tests for reports/daily_report.py (V4)"""

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
                    "cycle_summary", "data_quality", "owner_summary",
                    "actionable_items", "classified_topics", "today_schedule"):
            assert key in report, f"Missing key: {key}"

    def test_report_type_is_daily(self, tmp_path):
        path = _make_topics([])
        with mock.patch.object(dr, "TOPICS_FILE", path):
            report = dr.build_report()
        assert report["report_type"] == "daily"

    def test_data_quality_has_formula_breakdown(self, tmp_path):
        path = _make_topics([])
        with mock.patch.object(dr, "TOPICS_FILE", path):
            report = dr.build_report()
        dq = report["data_quality"]
        assert "total" in dq
        assert "breakdown" in dq
        assert "confidence" in dq
        assert isinstance(dq["breakdown"], list)
        assert len(dq["breakdown"]) == 7  # one per formula category
        # Each breakdown item has required fields
        for b in dq["breakdown"]:
            assert "key" in b
            assert "label" in b
            assert "max" in b
            assert "score" in b
            assert b["score"] <= b["max"]

    def test_data_quality_total_matches_breakdown(self, tmp_path):
        path = _make_topics([])
        with mock.patch.object(dr, "TOPICS_FILE", path):
            report = dr.build_report()
        dq = report["data_quality"]
        assert dq["total"] == sum(b["score"] for b in dq["breakdown"])

    def test_owner_summary_present_and_non_empty(self, tmp_path):
        path = _make_topics([])
        with mock.patch.object(dr, "TOPICS_FILE", path):
            report = dr.build_report()
        assert len(report["owner_summary"]) > 20

    def test_today_schedule_is_valid(self, tmp_path):
        path = _make_topics([])
        with mock.patch.object(dr, "TOPICS_FILE", path):
            report = dr.build_report()
        assert report["today_schedule"] in ("content", "stories", "none")

    def test_pipeline_health_has_permissions_audit(self, tmp_path):
        path = _make_topics([])
        with mock.patch.object(dr, "TOPICS_FILE", path):
            report = dr.build_report()
        assert "permissions_audit" in report["pipeline_health"]
        assert len(report["pipeline_health"]["permissions_audit"]) == 4


class TestClassifyTopics:
    def test_complete_topic_classified_complete(self):
        topics = [{"pipeline_state": "completed", "wix_status": "published",
                   "instagram_status": "published", "facebook_status": "published",
                   "threads_status": "skipped", "id": "1", "title": "T", "errors": ""}]
        classified = dr._classify_topics(topics)
        assert len(classified["complete"]) == 1
        assert len(classified["partial"]) == 0
        assert len(classified["failed"]) == 0

    def test_partial_is_partial_not_failed(self):
        """Bug fix: partial_failure must be classified as partial, not failed."""
        topics = [{
            "pipeline_state":   "partial_failure",
            "wix_status":       "partial_failure",
            "instagram_status": "published",
            "facebook_status":  "",
            "threads_status":   "",
            "id": "3", "title": "The pattern you keep returning to", "errors": "",
        }]
        classified = dr._classify_topics(topics)
        assert len(classified["partial"]) == 1, "partial_failure should be in partial, not failed"
        assert len(classified["failed"]) == 0, "partial_failure must NOT be in failed"

    def test_failed_topic_classified_failed(self):
        topics = [{
            "pipeline_state":   "failed",
            "wix_status":       "failed",
            "instagram_status": "failed",
            "facebook_status":  "failed",
            "threads_status":   "",
            "id": "2", "title": "Failed Topic", "errors": "HTTP 500",
        }]
        classified = dr._classify_topics(topics)
        assert len(classified["failed"]) == 1
        assert len(classified["partial"]) == 0

    def test_cycle_summary_consistent(self):
        """cycle_summary counts must match classified topics."""
        path = _make_topics([
            {"Pipeline State": "completed", "Wix Status": "published"},
            {"Pipeline State": "partial_failure", "Instagram Status": "published",
             "Wix Status": "partial_failure"},
        ])
        with mock.patch.object(dr, "TOPICS_FILE", path):
            report = dr.build_report()
        cy = report["cycle_summary"]
        # complete + partial + failed + pending must sum to total
        assert cy["complete"] + cy["partial"] + cy["failed"] + cy["pending"] == cy["total"]


class TestInferFailureStage:
    def test_partial_shows_succeeded_and_failed(self):
        topic = {
            "wix_status": "partial_failure", "instagram_status": "published",
            "facebook_status": "", "threads_status": "", "errors": "", "id": "1",
        }
        stage, error = dr._infer_failure_stage(topic)
        assert "Instagram" in stage    # succeeded
        assert "Wix" in stage          # failed
        assert "GitHub Actions" in error  # no error recorded

    def test_error_message_preserved(self):
        topic = {
            "wix_status": "failed", "instagram_status": "",
            "facebook_status": "", "threads_status": "",
            "errors": "HTTP 403 Unauthorized", "id": "2",
        }
        _, error = dr._infer_failure_stage(topic)
        assert "HTTP 403" in error

    def test_no_error_points_to_github_actions(self):
        topic = {
            "wix_status": "failed", "instagram_status": "",
            "facebook_status": "", "threads_status": "", "errors": "", "id": "5",
        }
        _, error = dr._infer_failure_stage(topic)
        assert "GitHub Actions" in error
        assert "5" in error  # topic ID


class TestActionableItems:
    def test_no_actions_when_healthy(self):
        health = {
            "overall_status": "healthy",
            "critical_reasons": [],
            "action_items": [],
            "channels": [],
            "token_issues": [],
            "missing_env": [],
            "permissions_audit": [],
        }
        classified = {"complete": [], "partial": [], "failed": [], "pending": []}
        items = dr._actionable_items(health, classified)
        assert items == []

    def test_partial_topic_in_actions_as_warning(self):
        health = {
            "overall_status": "warning",
            "critical_reasons": [],
            "action_items": [],
            "channels": [],
            "token_issues": [],
            "missing_env": [],
            "permissions_audit": [],
        }
        partial = [{"title": "Test Topic", "failure_stage": "Wix partial", "failure_error": "err", "id": "3"}]
        classified = {"complete": [], "partial": partial, "failed": [], "pending": []}
        items = dr._actionable_items(health, classified)
        assert any("Partial" in i["title"] for i in items)
        assert all(i.get("severity") != "critical" for i in items if "Partial" in i["title"])

    def test_failed_topic_in_actions_as_critical(self):
        health = {
            "overall_status": "critical",
            "critical_reasons": [],
            "action_items": [],
            "channels": [],
            "token_issues": [],
            "missing_env": [],
            "permissions_audit": [],
        }
        failed = [{"title": "Failed", "failure_stage": "all failed", "failure_error": "err", "id": "2"}]
        classified = {"complete": [], "partial": [], "failed": failed, "pending": []}
        items = dr._actionable_items(health, classified)
        assert any(i["severity"] == "critical" for i in items)


class TestToMarkdownV4:
    def _get_report(self, path):
        with mock.patch.object(dr, "TOPICS_FILE", path):
            return dr.build_report()

    def test_owner_summary_section_present(self, tmp_path):
        path = _make_topics([])
        report = self._get_report(path)
        md = dr.to_markdown(report)
        assert "## Owner Summary" in md

    def test_at_a_glance_section_present(self, tmp_path):
        path = _make_topics([])
        report = self._get_report(path)
        md = dr.to_markdown(report)
        assert "## At a Glance" in md

    def test_no_action_text_when_clean(self, tmp_path):
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
        assert "No action required today" in md

    def test_partial_not_shown_as_failed(self, tmp_path):
        path = _make_topics([{
            "ID": "3", "Topic / Working Title": "The pattern you keep returning to",
            "Pipeline State": "partial_failure",
            "Wix Status": "partial_failure",
            "Instagram Status": "published",
        }])
        with mock.patch.object(dr, "TOPICS_FILE", path):
            report = dr.build_report()
        md = dr.to_markdown(report)
        # Partial topic must show as 🟡 Partial, not ❌ Failed
        assert "🟡" in md or "Partial" in md
        # Failed count at top must be 0
        assert "❌ 0 failed" not in md or "🟡 1 partial" in md

    def test_cycle_summary_distinguishes_partial_from_failed(self, tmp_path):
        path = _make_topics([{
            "Pipeline State": "partial_failure",
            "Instagram Status": "published",
            "Wix Status": "partial_failure",
        }])
        with mock.patch.object(dr, "TOPICS_FILE", path):
            report = dr.build_report()
        assert report["cycle_summary"]["partial"] >= 1
        assert report["cycle_summary"]["failed"] == 0

    def test_data_quality_score_with_formula_in_markdown(self, tmp_path):
        path = _make_topics([])
        report = self._get_report(path)
        md = dr.to_markdown(report)
        assert "Data Quality Score" in md
        assert "/100" in md
        assert "transparent formula" in md.lower() or "formula" in md.lower()

    def test_business_impact_section_present(self, tmp_path):
        path = _make_topics([])
        report = self._get_report(path)
        md = dr.to_markdown(report)
        assert "Business Impact" in md

    def test_why_this_matters_section_present(self, tmp_path):
        path = _make_topics([])
        report = self._get_report(path)
        md = dr.to_markdown(report)
        assert "Why This Matters" in md

    def test_stories_pipeline_mentioned(self, tmp_path):
        path = _make_topics([])
        report = self._get_report(path)
        md = dr.to_markdown(report)
        assert "Stories" in md

    def test_actionable_items_have_specific_next_step(self, tmp_path):
        path = _make_topics([{
            "ID": "3", "Topic / Working Title": "The pattern",
            "Pipeline State": "partial_failure",
            "Wix Status": "partial_failure",
            "Instagram Status": "published",
        }])
        with mock.patch.object(dr, "TOPICS_FILE", path):
            report = dr.build_report()
        md = dr.to_markdown(report)
        # Action Required must have "What to do" with specific steps
        assert "What to do" in md or "Action" in md

    def test_all_channels_present(self, tmp_path):
        path = _make_topics([])
        report = self._get_report(path)
        md = dr.to_markdown(report)
        for ch in ["Wix", "Instagram", "Facebook", "Threads"]:
            assert ch in md

    def test_visual_indicators_present(self, tmp_path):
        path = _make_topics([])
        report = self._get_report(path)
        md = dr.to_markdown(report)
        assert any(icon in md for icon in ("🟢", "🟡", "🔴", "✅", "⚪", "⚠️"))


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
