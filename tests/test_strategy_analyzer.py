"""Tests for strategy/strategy_analyzer.py"""

import csv
import json
import tempfile
from datetime import date
from pathlib import Path
from unittest import mock

import pytest

import strategy.strategy_analyzer as sa


def _make_topics(rows: list[dict]) -> Path:
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="")
    fieldnames = [
        "ID", "Date Added", "Topic / Working Title", "Status", "Pipeline State",
        "Content Pillar", "Wix Status", "Instagram Status", "Facebook Status", "Threads Status",
        "Publication Errors",
    ]
    writer = csv.DictWriter(tmp, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow({f: row.get(f, "") for f in fieldnames})
    tmp.close()
    return Path(tmp.name)


class TestAnalyze:
    def test_returns_required_keys(self, tmp_path):
        path = _make_topics([])
        with mock.patch.object(sa, "TOPICS_FILE", path), \
             mock.patch.object(sa, "THREADS_POSTS", tmp_path / "posts.csv"), \
             mock.patch.object(sa, "THREADS_COMMENTS", tmp_path / "comments.csv"), \
             mock.patch.object(sa, "PROMPT_LOG", tmp_path / "log.csv"):
            result = sa.analyze()
        for key in ["analysis_date", "cycle_summary", "facts", "interpretation", "recommendations"]:
            assert key in result

    def test_separates_published_from_failed(self, tmp_path):
        rows = [
            {"Topic / Working Title": "P1", "Status": "Published", "Pipeline State": "completed"},
            {"Topic / Working Title": "F1", "Status": "Failed", "Pipeline State": "failed"},
            {"Topic / Working Title": "R1", "Status": "Ready", "Pipeline State": ""},
        ]
        path = _make_topics(rows)
        with mock.patch.object(sa, "TOPICS_FILE", path), \
             mock.patch.object(sa, "THREADS_POSTS", tmp_path / "posts.csv"), \
             mock.patch.object(sa, "THREADS_COMMENTS", tmp_path / "comments.csv"), \
             mock.patch.object(sa, "PROMPT_LOG", tmp_path / "log.csv"):
            result = sa.analyze()
        assert result["cycle_summary"]["published_topics"] >= 1
        assert result["cycle_summary"]["failed_topics"] >= 1

    def test_weak_signal_noted_when_few_comments(self, tmp_path):
        path = _make_topics([])
        with mock.patch.object(sa, "TOPICS_FILE", path), \
             mock.patch.object(sa, "THREADS_POSTS", tmp_path / "posts.csv"), \
             mock.patch.object(sa, "THREADS_COMMENTS", tmp_path / "comments.csv"), \
             mock.patch.object(sa, "PROMPT_LOG", tmp_path / "log.csv"):
            result = sa.analyze()
        notes = result["interpretation"]["what_is_unclear_due_to_missing_data"]
        assert any("WEAK SIGNAL" in n for n in notes)

    def test_no_data_note_for_missing_instagram(self, tmp_path):
        path = _make_topics([])
        with mock.patch.object(sa, "TOPICS_FILE", path), \
             mock.patch.object(sa, "THREADS_POSTS", tmp_path / "posts.csv"), \
             mock.patch.object(sa, "THREADS_COMMENTS", tmp_path / "comments.csv"), \
             mock.patch.object(sa, "PROMPT_LOG", tmp_path / "log.csv"):
            result = sa.analyze()
        notes = result["interpretation"]["what_is_unclear_due_to_missing_data"]
        assert any("NO DATA" in n and "Instagram" in n for n in notes)


class TestToMarkdown:
    def test_markdown_has_sections(self, tmp_path):
        path = _make_topics([])
        with mock.patch.object(sa, "TOPICS_FILE", path), \
             mock.patch.object(sa, "THREADS_POSTS", tmp_path / "posts.csv"), \
             mock.patch.object(sa, "THREADS_COMMENTS", tmp_path / "comments.csv"), \
             mock.patch.object(sa, "PROMPT_LOG", tmp_path / "log.csv"):
            diagnosis = sa.analyze()
        md = sa.to_markdown(diagnosis)
        assert "Facts" in md
        assert "Interpretation" in md
        assert "Recommendations" in md

    def test_markdown_contains_date(self, tmp_path):
        path = _make_topics([])
        with mock.patch.object(sa, "TOPICS_FILE", path), \
             mock.patch.object(sa, "THREADS_POSTS", tmp_path / "posts.csv"), \
             mock.patch.object(sa, "THREADS_COMMENTS", tmp_path / "comments.csv"), \
             mock.patch.object(sa, "PROMPT_LOG", tmp_path / "log.csv"):
            diagnosis = sa.analyze()
        md = sa.to_markdown(diagnosis)
        assert diagnosis["analysis_date"] in md
