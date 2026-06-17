"""Tests for reports/weekly_strategy_report.py"""

import csv
import json
import os
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import pytest

import reports.weekly_strategy_report as wr


def _make_topics(rows: list[dict]) -> Path:
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="")
    fieldnames = [
        "ID", "Date Added", "Topic / Working Title", "Status", "Pipeline State",
        "Wix Status", "Instagram Status", "Facebook Status", "Threads Status",
        "Published URL", "Website Published URL", "Instagram Published URL",
        "Threads External ID", "FB Message", "Publish Status Code",
        "Publication Errors", "Last Error", "Retry Available",
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
        with mock.patch.object(wr, "TOPICS_FILE", path):
            report = wr.build_report()
        for key in ["report_type", "report_date", "week_start", "channel_performance",
                    "topic_inventory", "facts", "interpretation", "operational_issues"]:
            assert key in report, f"Missing key: {key}"

    def test_report_type_is_weekly(self, tmp_path):
        path = _make_topics([])
        with mock.patch.object(wr, "TOPICS_FILE", path):
            report = wr.build_report()
        assert report["report_type"] == "weekly"

    def test_week_start_is_7_days_ago(self, tmp_path):
        path = _make_topics([])
        with mock.patch.object(wr, "TOPICS_FILE", path):
            report = wr.build_report()
        assert report["week_start"] == (date.today() - timedelta(days=7)).isoformat()

    def test_published_topics_appear_in_facts(self, tmp_path):
        path = _make_topics([{
            "Topic / Working Title": "Test Topic",
            "Pipeline State": "completed",
            "Date Added": date.today().isoformat(),
        }])
        with mock.patch.object(wr, "TOPICS_FILE", path):
            report = wr.build_report()
        assert "Test Topic" in report["facts"]["published_topics"]

    def test_interpretation_has_confidence(self, tmp_path):
        path = _make_topics([])
        with mock.patch.object(wr, "TOPICS_FILE", path):
            report = wr.build_report()
        assert "confidence" in report["interpretation"]
        assert report["interpretation"]["confidence"] in ("Low", "Medium", "High")

    def test_interpretation_has_confidence_reason(self, tmp_path):
        path = _make_topics([])
        with mock.patch.object(wr, "TOPICS_FILE", path):
            report = wr.build_report()
        assert "confidence_reason" in report["interpretation"]
        assert len(report["interpretation"]["confidence_reason"]) > 5

    def test_threads_posts_this_week_key_present(self, tmp_path):
        path = _make_topics([])
        with mock.patch.object(wr, "TOPICS_FILE", path):
            report = wr.build_report()
        assert "posts_this_week" in report["threads_insights"]

    def test_permissions_audit_in_health_summary(self, tmp_path):
        path = _make_topics([])
        with mock.patch.object(wr, "TOPICS_FILE", path):
            report = wr.build_report()
        assert "permissions_audit" in report["pipeline_health_summary"]


class TestThreadsContradiction:
    def test_zero_posts_this_week_shows_no_current_best(self, tmp_path):
        """If 0 Threads posts this week, best_performing_this_week must be empty."""
        path = _make_topics([])
        with mock.patch.object(wr, "TOPICS_FILE", path), \
             mock.patch.object(wr, "THREADS_POSTS", tmp_path / "none.csv"):
            report = wr.build_report()
        assert report["threads_insights"]["best_performing_this_week"] == []

    def test_all_zero_scores_flagged(self, tmp_path):
        """If all Threads post scores are 0, all_scores_zero must be True."""
        path = _make_topics([])
        mock_threads_data = {
            "best_performing_posts": [
                {"post_id": "a", "score": 0, "text_preview": "test"},
                {"post_id": "b", "score": 0, "text_preview": "test2"},
            ]
        }
        with mock.patch.object(wr, "TOPICS_FILE", path), \
             mock.patch("reports.weekly_strategy_report._load_threads_data", return_value=mock_threads_data), \
             mock.patch("reports.weekly_strategy_report._threads_posts_this_week", return_value=[]):
            report = wr.build_report()
        assert report["threads_insights"]["all_scores_zero"] is True


class TestToMarkdownV2:
    def _get_report(self, path):
        with mock.patch.object(wr, "TOPICS_FILE", path):
            return wr.build_report()

    def test_action_required_section_always_present(self, tmp_path):
        path = _make_topics([])
        report = self._get_report(path)
        md = wr.to_markdown(report)
        assert "## Action Required" in md

    def test_facts_section_present(self, tmp_path):
        path = _make_topics([])
        report = self._get_report(path)
        md = wr.to_markdown(report)
        assert "## Facts" in md

    def test_interpretation_section_present(self, tmp_path):
        path = _make_topics([])
        report = self._get_report(path)
        md = wr.to_markdown(report)
        assert "## Interpretation" in md

    def test_confidence_in_interpretation(self, tmp_path):
        path = _make_topics([])
        report = self._get_report(path)
        md = wr.to_markdown(report)
        assert "Confidence" in md
        assert any(level in md for level in ("Low", "Medium", "High"))

    def test_permissions_table_present(self, tmp_path):
        path = _make_topics([])
        report = self._get_report(path)
        md = wr.to_markdown(report)
        assert "## Permissions & Data Availability" in md

    def test_recommended_next_actions_present(self, tmp_path):
        path = _make_topics([])
        report = self._get_report(path)
        md = wr.to_markdown(report)
        assert "## Recommended Next Actions" in md

    def test_no_current_best_posts_when_zero_threads_this_week(self, tmp_path):
        """Markdown must not show current-week best posts when threads_posts_this_week == 0."""
        path = _make_topics([])
        with mock.patch.object(wr, "TOPICS_FILE", path), \
             mock.patch.object(wr, "THREADS_POSTS", tmp_path / "empty.csv"):
            report = wr.build_report()
        md = wr.to_markdown(report)
        # Should NOT say "Best performing posts this week"
        assert "Best performing posts this week:" not in md

    def test_all_zero_scores_labeled_no_signal(self, tmp_path):
        """If all scores are 0, markdown must say no meaningful performance signal."""
        path = _make_topics([])
        mock_threads_data = {
            "best_performing_posts": [{"post_id": "a", "score": 0, "text_preview": "test"}]
        }
        with mock.patch.object(wr, "TOPICS_FILE", path), \
             mock.patch("reports.weekly_strategy_report._load_threads_data", return_value=mock_threads_data), \
             mock.patch("reports.weekly_strategy_report._threads_posts_this_week", return_value=[]):
            report = wr.build_report()
        md = wr.to_markdown(report)
        assert "No meaningful performance signal yet" in md

    def test_critical_reasons_shown_when_critical(self, tmp_path):
        path = _make_topics([])
        with mock.patch.object(wr, "TOPICS_FILE", path):
            report = wr.build_report()
        report["pipeline_health_summary"]["overall_status"] = "critical"
        report["pipeline_health_summary"]["critical_reasons"] = ["Token expired.", "No publish in 10 days."]
        md = wr.to_markdown(report)
        assert "## Critical Reasons" in md
        assert "Token expired." in md

    def test_critical_section_absent_when_healthy(self, tmp_path):
        path = _make_topics([])
        with mock.patch.object(wr, "TOPICS_FILE", path):
            report = wr.build_report()
        report["pipeline_health_summary"]["overall_status"] = "healthy"
        report["pipeline_health_summary"]["critical_reasons"] = []
        md = wr.to_markdown(report)
        assert "## Critical Reasons" not in md

    def test_days_left_explanation_in_markdown(self, tmp_path):
        path = _make_topics([])
        report = self._get_report(path)
        md = wr.to_markdown(report)
        assert "cadence" in md.lower() or "Estimated runway" in md

    def test_all_channels_present(self, tmp_path):
        path = _make_topics([])
        report = self._get_report(path)
        md = wr.to_markdown(report)
        for ch in ["Wix", "Instagram", "Facebook", "Threads"]:
            assert ch in md


class TestSaveReport:
    def test_saves_json_and_md(self, tmp_path):
        path = _make_topics([])
        with mock.patch.object(wr, "TOPICS_FILE", path), \
             mock.patch.object(wr, "REPORTS_DIR", tmp_path):
            report = wr.build_report()
            md = wr.to_markdown(report)
            json_path, md_path = wr.save_report(report, md)
        assert json_path.exists()
        assert md_path.exists()

    def test_run_does_not_raise_on_email_fail(self, tmp_path):
        path = _make_topics([])
        with mock.patch.object(wr, "TOPICS_FILE", path), \
             mock.patch.object(wr, "REPORTS_DIR", tmp_path), \
             mock.patch("reports.weekly_strategy_report.send_weekly_report", return_value=False):
            result = wr.run(send_email=True)
        assert result["report_type"] == "weekly"
