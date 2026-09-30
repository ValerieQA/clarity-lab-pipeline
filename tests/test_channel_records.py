"""What each channel must leave behind, and which topic it should pick.

These are client-agnostic: nothing here knows that the client is Clarity Lab,
and adding a channel should not require editing a mapping table.
"""

from __future__ import annotations

import csv
import sys
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from publication_state import (  # noqa: E402
    PublicationState,
    ensure_topic_state_fields,
    external_id_field,
    write_topics,
)

FAKE_ENV = {
    "OPENAI_API_KEY": "test", "CLOUDINARY_CLOUD_NAME": "test",
    "CLOUDINARY_API_KEY": "test", "CLOUDINARY_API_SECRET": "test",
    "WIX_SITE_ID": "test", "WIX_API_KEY": "test",
    "IG_USER_ID": "test", "IG_TOKEN": "test",
    "FB_PAGE_ID": "test", "FB_PAGE_TOKEN": "test",
}


def _load(module_name, monkeypatch):
    monkeypatch.chdir(ROOT)
    for key, value in FAKE_ENV.items():
        monkeypatch.setenv(key, value)
    sys.modules.pop(module_name, None)
    return __import__(module_name)


# --------------------------------------------------------------------------
# Post ids
# --------------------------------------------------------------------------

@pytest.mark.parametrize("platform,column", [
    ("instagram", "Instagram Post ID"),
    ("facebook", "Facebook Post ID"),
    ("threads", "Threads External ID"),
    ("telegram", "Telegram Post ID"),
])
def test_id_column_is_derived_from_the_platform_name(platform, column):
    """A channel added later needs no entry in a mapping to be recorded."""
    assert external_id_field(platform) == column


def test_a_column_written_to_one_row_survives_the_write():
    """Union of keys, not the first row's keys — otherwise ids are dropped."""
    rows = [{"ID": "1"}, {"ID": "2", "Telegram Post ID": "t-42"}]
    fieldnames = ensure_topic_state_fields(rows)
    assert "Telegram Post ID" in fieldnames


def test_published_ids_reach_topics_csv(monkeypatch, tmp_path):
    pipeline = _load("pipeline", monkeypatch)

    topics = tmp_path / "topics.csv"
    rows = [{
        "ID": "1", "Topic / Working Title": "t", "Status": "Ready",
        "Website Published URL": "", "Instagram Post ID": "", "Facebook Post ID": "",
    }]
    write_topics(str(topics), rows)
    monkeypatch.setattr(pipeline, "TOPICS_FILE", str(topics))

    state = PublicationState(topic_id="1")
    state.set_platform("wix", True, "published", url="https://example.com/post")
    state.set_platform("instagram", True, "published", external_id="ig-17999")
    state.set_platform("facebook", True, "published", external_id="fb-12213")

    rows = list(csv.DictReader(topics.open(newline="", encoding="utf-8")))
    pipeline.mark_topic_state(0, rows, "https://example.com/post", "https://img", state)

    written = list(csv.DictReader(topics.open(newline="", encoding="utf-8")))[0]
    assert written["Instagram Post ID"] == "ig-17999"
    assert written["Facebook Post ID"] == "fb-12213"
    assert written["Status"] == "Published"


def test_a_failed_channel_records_no_id(monkeypatch, tmp_path):
    pipeline = _load("pipeline", monkeypatch)

    topics = tmp_path / "topics.csv"
    write_topics(str(topics), [{"ID": "1", "Topic / Working Title": "t", "Status": "Ready"}])
    monkeypatch.setattr(pipeline, "TOPICS_FILE", str(topics))

    state = PublicationState(topic_id="1")
    state.set_platform("instagram", True, "failed", error="Container error")
    state.set_platform("facebook", True, "published", external_id="fb-1")

    rows = list(csv.DictReader(topics.open(newline="", encoding="utf-8")))
    pipeline.mark_topic_state(0, rows, "", "", state)

    written = list(csv.DictReader(topics.open(newline="", encoding="utf-8")))[0]
    assert written["Instagram Post ID"] == ""
    assert written["Facebook Post ID"] == "fb-1"
    assert written["Status"] == "Partial Failure"


# --------------------------------------------------------------------------
# LinkedIn: topic rotation and the dormant channel
# --------------------------------------------------------------------------

def _linkedin_with_topics(monkeypatch, tmp_path, titles):
    linkedin = _load("linkedin", monkeypatch)
    topics = tmp_path / "topics.csv"
    with topics.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["ID", "Topic / Working Title", "Status"])
        writer.writeheader()
        for i, title in enumerate(titles, 1):
            writer.writerow({"ID": str(i), "Topic / Working Title": title, "Status": "Published"})
    monkeypatch.setattr(linkedin, "TOPICS_FILE", topics)
    return linkedin


def test_an_untouched_topic_is_preferred(monkeypatch, tmp_path):
    linkedin = _linkedin_with_topics(monkeypatch, tmp_path, ["first", "second", "third"])
    history = [{"source_topic": "first", "created_at": "2026-09-01T00:00:00"}]

    assert linkedin._next_topic(history)["Topic / Working Title"] in {"second", "third"}


def test_the_least_recently_drafted_topic_comes_next(monkeypatch, tmp_path):
    linkedin = _linkedin_with_topics(monkeypatch, tmp_path, ["first", "second", "third"])
    history = [
        {"source_topic": "first", "created_at": "2026-09-20T00:00:00"},
        {"source_topic": "second", "created_at": "2026-09-01T00:00:00"},
        {"source_topic": "third", "created_at": "2026-09-10T00:00:00"},
    ]

    assert linkedin._next_topic(history)["Topic / Working Title"] == "second"


def test_the_same_topic_is_not_returned_twice_in_a_row(monkeypatch, tmp_path):
    """The bug: five drafts in a row about the first row of topics.csv."""
    linkedin = _linkedin_with_topics(monkeypatch, tmp_path, ["first", "second"])
    history: list[dict] = []

    picked = []
    for day in range(4):
        topic = linkedin._next_topic(history)["Topic / Working Title"]
        picked.append(topic)
        history.append({"source_topic": topic, "created_at": f"2026-09-{day + 1:02d}T00:00:00"})

    assert picked == ["first", "second", "first", "second"]


def test_without_a_token_the_channel_generates_nothing(monkeypatch):
    linkedin = _load("linkedin", monkeypatch)
    monkeypatch.setattr(linkedin, "LI", replace(linkedin.LI, access_token=""))
    monkeypatch.setattr(sys, "argv", ["linkedin.py"])

    def fail(*args, **kwargs):
        raise AssertionError("a dormant channel must not call the model")

    monkeypatch.setattr(linkedin, "create_draft", fail)
    assert linkedin.main() == 0


def test_with_a_token_the_channel_runs(monkeypatch):
    linkedin = _load("linkedin", monkeypatch)
    monkeypatch.setattr(linkedin, "LI", replace(linkedin.LI, access_token="token"))
    monkeypatch.setattr(sys, "argv", ["linkedin.py"])

    called = []
    monkeypatch.setattr(linkedin, "create_draft", lambda: called.append(True))
    assert linkedin.main() == 0
    assert called == [True]
