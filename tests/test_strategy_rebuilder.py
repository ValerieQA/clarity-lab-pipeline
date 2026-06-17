"""Tests for strategy/strategy_rebuilder.py"""

import csv
import json
import tempfile
from pathlib import Path
from unittest import mock

import pytest

import strategy.strategy_rebuilder as sr


def _make_topics(rows: list[dict]) -> Path:
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="")
    fieldnames = [
        "ID", "Date Added", "Topic / Working Title", "Status", "Pipeline State",
        "Content Pillar", "Wix Status", "Instagram Status", "Facebook Status", "Threads Status",
    ]
    writer = csv.DictWriter(tmp, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow({f: row.get(f, "") for f in fieldnames})
    tmp.close()
    return Path(tmp.name)


class TestBuild:
    def test_returns_required_keys(self, tmp_path):
        path = _make_topics([])
        env = {"TOPICS_FILE": str(path)}
        with mock.patch.dict("os.environ", env, clear=False), \
             mock.patch.object(sr, "TOPICS_FILE", path), \
             mock.patch("strategy.strategy_rebuilder.run_analysis", return_value={
                 "analysis_date": "2026-06-16",
                 "cycle_summary": {"published_topics": 5, "failed_topics": 1, "remaining_topics": 0},
                 "facts": {"top_content_pillars": ["clarity"], "comment_themes": ["understanding"],
                           "failed_topic_titles": [], "threads_comments_count": 0},
                 "interpretation": {"what_strategy_was_tested": "test", "comment_topics_worth_continuing": [],
                                    "what_is_unclear_due_to_missing_data": []},
                 "recommendations": {"continue": [], "stop_or_test_differently": [], "missing_data_to_resolve": []}
             }), \
             mock.patch("strategy.strategy_rebuilder.run_research", return_value={
                 "brief": "test brief", "brief_date": "2026-06-16",
                 "diagnosis_date": "2026-06-16", "remaining_topics": 0
             }), \
             mock.patch.dict("os.environ", {"OPENAI_API_KEY": ""}, clear=False):
            result = sr.build()
        for key in ["rebuild_date", "cycle_id", "strategy_document", "proposed_topics", "topics_count"]:
            assert key in result

    def test_proposed_topics_not_overwrite_active(self, tmp_path):
        """Proposed topics must be saved separately, never to topics.csv."""
        path = _make_topics([{"Topic / Working Title": "Existing Topic", "Status": "Ready"}])
        with mock.patch.object(sr, "TOPICS_FILE", path), \
             mock.patch.object(sr, "STRATEGY_DIR", tmp_path), \
             mock.patch("strategy.strategy_rebuilder.run_analysis", return_value={
                 "analysis_date": "2026-06-16",
                 "cycle_summary": {},
                 "facts": {"top_content_pillars": [], "comment_themes": [], "failed_topic_titles": []},
                 "interpretation": {"what_strategy_was_tested": "test",
                                    "comment_topics_worth_continuing": [],
                                    "what_is_unclear_due_to_missing_data": []},
                 "recommendations": {"continue": [], "stop_or_test_differently": [], "missing_data_to_resolve": []}
             }), \
             mock.patch("strategy.strategy_rebuilder.run_research", return_value={
                 "brief": "brief", "brief_date": "2026-06-16",
                 "diagnosis_date": "2026-06-16", "remaining_topics": 0
             }), \
             mock.patch.dict("os.environ", {"OPENAI_API_KEY": ""}, clear=False):
            result = sr.build()
            sr.save(result)

        # topics.csv must remain unchanged
        with path.open() as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["Topic / Working Title"] == "Existing Topic"

        # Proposed topics must be in data/strategy/
        proposed = list(tmp_path.glob("proposed_topics_*.csv"))
        assert len(proposed) == 1

    def test_proposed_topics_have_correct_schema(self, tmp_path):
        path = _make_topics([])
        with mock.patch.object(sr, "TOPICS_FILE", path), \
             mock.patch.object(sr, "STRATEGY_DIR", tmp_path), \
             mock.patch("strategy.strategy_rebuilder.run_analysis", return_value={
                 "analysis_date": "2026-06-16", "cycle_summary": {},
                 "facts": {"top_content_pillars": [], "comment_themes": [], "failed_topic_titles": []},
                 "interpretation": {"what_strategy_was_tested": "x",
                                    "comment_topics_worth_continuing": [],
                                    "what_is_unclear_due_to_missing_data": []},
                 "recommendations": {"continue": [], "stop_or_test_differently": [], "missing_data_to_resolve": []}
             }), \
             mock.patch("strategy.strategy_rebuilder.run_research", return_value={
                 "brief": "", "brief_date": "2026-06-16",
                 "diagnosis_date": "2026-06-16", "remaining_topics": 0
             }), \
             mock.patch.dict("os.environ", {"OPENAI_API_KEY": ""}, clear=False):
            result = sr.build()
            sr.save(result)

        proposed = list(tmp_path.glob("proposed_topics_*.csv"))[0]
        with proposed.open() as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 30
        required_fields = ["topic_id", "title", "status", "created_at", "strategy_cycle_id"]
        for field in required_fields:
            assert field in rows[0], f"Missing field: {field}"

    def test_status_is_proposed_not_ready(self, tmp_path):
        path = _make_topics([])
        with mock.patch.object(sr, "TOPICS_FILE", path), \
             mock.patch.object(sr, "STRATEGY_DIR", tmp_path), \
             mock.patch("strategy.strategy_rebuilder.run_analysis", return_value={
                 "analysis_date": "2026-06-16", "cycle_summary": {},
                 "facts": {"top_content_pillars": [], "comment_themes": [], "failed_topic_titles": []},
                 "interpretation": {"what_strategy_was_tested": "x",
                                    "comment_topics_worth_continuing": [],
                                    "what_is_unclear_due_to_missing_data": []},
                 "recommendations": {"continue": [], "stop_or_test_differently": [], "missing_data_to_resolve": []}
             }), \
             mock.patch("strategy.strategy_rebuilder.run_research", return_value={
                 "brief": "", "brief_date": "2026-06-16",
                 "diagnosis_date": "2026-06-16", "remaining_topics": 0
             }), \
             mock.patch.dict("os.environ", {"OPENAI_API_KEY": ""}, clear=False):
            result = sr.build()
        assert all(t["status"] == "proposed" for t in result["proposed_topics"])
