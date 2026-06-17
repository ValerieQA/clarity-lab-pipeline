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
        with mock.patch.object(dr, "TOPICS_FILE", path), \
             mock.patch.object(dr, "REPORTS_DIR", tmp_path / "reports/daily"):
            report = dr.build_report()
        assert "report_type" in report
        assert "report_date" in report
        assert "topic_inventory" in report
        assert "pipeline_health" in report
        assert "today_activity" in report

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


class TestToMarkdown:
    def test_markdown_contains_date(self, tmp_path):
        path = _make_topics([])
        with mock.patch.object(dr, "TOPICS_FILE", path):
            report = dr.build_report()
        md = dr.to_markdown(report)
        assert dr.TODAY.isoformat() in md

    def test_markdown_contains_channel_breakdown(self, tmp_path):
        path = _make_topics([])
        with mock.patch.object(dr, "TOPICS_FILE", path):
            report = dr.build_report()
        md = dr.to_markdown(report)
        assert "Wix" in md
        assert "Instagram" in md
        assert "Facebook" in md
        assert "Threads" in md


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
