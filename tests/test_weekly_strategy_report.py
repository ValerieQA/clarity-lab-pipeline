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
                    "topic_inventory", "strategy_signals", "operational_issues"]:
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

    def test_published_topics_appear_in_signals(self, tmp_path):
        path = _make_topics([{
            "Topic / Working Title": "Test Topic",
            "Pipeline State": "completed",
            "Date Added": date.today().isoformat(),
        }])
        with mock.patch.object(wr, "TOPICS_FILE", path):
            report = wr.build_report()
        assert "Test Topic" in report["strategy_signals"]["published_topics"]


class TestToMarkdown:
    def test_markdown_contains_all_channels(self, tmp_path):
        path = _make_topics([])
        with mock.patch.object(wr, "TOPICS_FILE", path):
            report = wr.build_report()
        md = wr.to_markdown(report)
        for ch in ["Wix", "Instagram", "Facebook", "Threads"]:
            assert ch in md

    def test_markdown_contains_week_dates(self, tmp_path):
        path = _make_topics([])
        with mock.patch.object(wr, "TOPICS_FILE", path):
            report = wr.build_report()
        md = wr.to_markdown(report)
        assert report["week_start"] in md

    def test_markdown_mentions_threads_only_note(self, tmp_path):
        path = _make_topics([])
        with mock.patch.object(wr, "TOPICS_FILE", path):
            report = wr.build_report()
        md = wr.to_markdown(report)
        # Should mention that only Threads data is available as signal
        assert "Threads" in md


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
