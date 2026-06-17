"""Tests for strategy/topic_inventory.py"""

import csv
import os
import tempfile
from pathlib import Path

import pytest

from strategy.topic_inventory import load_inventory, format_summary, THRESHOLD_CRITICAL, THRESHOLD_WARNING, THRESHOLD_NOTICE


def _make_topics_csv(rows: list[dict]) -> Path:
    """Write a minimal topics.csv to a temp file and return its path."""
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="")
    fieldnames = ["ID", "Topic / Working Title", "Status", "Pipeline State"]
    writer = csv.DictWriter(tmp, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow({f: row.get(f, "") for f in fieldnames})
    tmp.close()
    return Path(tmp.name)


def _row(id_: int, status: str, pipeline_state: str = "") -> dict:
    return {"ID": str(id_), "Topic / Working Title": f"Topic {id_}", "Status": status, "Pipeline State": pipeline_state}


class TestLoadInventoryCounts:
    def test_all_published(self):
        rows = [_row(i, "Published") for i in range(1, 6)]
        path = _make_topics_csv(rows)
        inv = load_inventory(path)
        assert inv["total_topics"] == 5
        assert inv["published_topics"] == 5
        assert inv["remaining_topics"] == 0

    def test_all_ready(self):
        rows = [_row(i, "Ready") for i in range(1, 16)]
        path = _make_topics_csv(rows)
        inv = load_inventory(path)
        assert inv["remaining_topics"] == 15
        assert inv["published_topics"] == 0

    def test_mixed(self):
        rows = (
            [_row(i, "Published") for i in range(1, 25)]
            + [_row(i, "Ready") for i in range(25, 31)]
        )
        path = _make_topics_csv(rows)
        inv = load_inventory(path)
        assert inv["total_topics"] == 30
        assert inv["published_topics"] == 24
        assert inv["remaining_topics"] == 6

    def test_failed_counted_separately(self):
        rows = [_row(1, "Published"), _row(2, "Partial Failure"), _row(3, "Ready")]
        path = _make_topics_csv(rows)
        inv = load_inventory(path)
        assert inv["failed_topics"] == 1
        assert inv["remaining_topics"] == 1

    def test_pipeline_state_takes_precedence(self):
        # Pipeline State = completed overrides Status = Ready
        rows = [_row(1, "Ready", pipeline_state="completed"), _row(2, "Ready")]
        path = _make_topics_csv(rows)
        inv = load_inventory(path)
        assert inv["published_topics"] == 1
        assert inv["remaining_topics"] == 1


class TestStatusThresholds:
    def test_healthy_above_notice(self):
        rows = [_row(i, "Ready") for i in range(1, 12)]  # 11 remaining
        inv = load_inventory(_make_topics_csv(rows))
        assert inv["status"] == "healthy"
        assert inv["action_required"] is False

    def test_notice_at_10(self):
        rows = [_row(i, "Ready") for i in range(1, 11)]  # 10 remaining
        inv = load_inventory(_make_topics_csv(rows))
        assert inv["status"] == "notice"
        assert inv["action_required"] is True

    def test_warning_at_5(self):
        rows = [_row(i, "Ready") for i in range(1, 6)]  # 5 remaining
        inv = load_inventory(_make_topics_csv(rows))
        assert inv["status"] == "warning"
        assert inv["action_required"] is True

    def test_warning_below_5(self):
        rows = [_row(i, "Ready") for i in range(1, 4)]  # 3 remaining
        inv = load_inventory(_make_topics_csv(rows))
        assert inv["status"] == "warning"

    def test_critical_at_zero(self):
        rows = [_row(i, "Published") for i in range(1, 6)]  # 0 remaining
        inv = load_inventory(_make_topics_csv(rows))
        assert inv["status"] == "critical"
        assert inv["action_required"] is True
        assert inv["remaining_topics"] == 0

    def test_missing_file_is_critical(self):
        inv = load_inventory(Path("/nonexistent/path/topics.csv"))
        assert inv["status"] == "critical"
        assert inv["action_required"] is True


class TestFormatSummary:
    def test_summary_contains_status(self):
        inv = {"status": "warning", "total_topics": 30, "published_topics": 25,
               "remaining_topics": 5, "failed_topics": 0, "days_left": 10,
               "next_topic": "Test topic", "message": "Only 5 topics remaining.", "action_required": True}
        summary = format_summary(inv)
        assert "WARNING" in summary
        assert "5" in summary
        assert "Test topic" in summary
