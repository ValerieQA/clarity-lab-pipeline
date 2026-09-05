"""Regression tests for the two defects that made the strategy engine lie.

1. The diagnosis reported "Threads: 0 published" while 111 posts were published,
   because it read a topics.csv column that threads.py never writes.
2. Stopwords from two comments were reported as audience themes, travelled into
   "what to continue", and from there into a proposed change of positioning.

Both produced confident-looking output from no evidence, which is worse than
producing nothing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from strategy.strategy_analyzer import (  # noqa: E402
    MIN_COMMENTS_FOR_THEMES,
    MIN_DISTINCT_SOURCES,
    MIN_WORD_OCCURRENCES,
    _top_words,
)


# --------------------------------------------------------------------------
# Defect 2 — noise reported as themes
# --------------------------------------------------------------------------

def test_no_themes_below_the_comment_threshold():
    """Two comments cannot produce a theme, however many words they share."""
    comments = [
        "Where do you start when that clarity isn't there? It's internal.",
        "It's internal, and it reduces the noise. It's internal.",
    ]
    assert _top_words(comments) == []


def test_the_exact_regression_case():
    """'internal', 'reduces' and \"it's\" were the real reported themes."""
    real_comments = [
        "Where do you start when that clarity isn't there? When there's brain fog. "
        "And how do you know what it means if you have a headache?",
        "What becomes visible is that naming internal states reduces cognitive "
        "uncertainty load. Unstructured emotion increases internal prediction effort.",
    ]
    themes = _top_words(real_comments)
    assert themes == [], f"noise came back as themes: {themes}"


def test_contraction_fragments_are_never_themes():
    texts = [f"it's here and that's fine, there's more {i}" for i in range(10)]
    for junk in ("it's", "that's", "there's"):
        assert junk not in _top_words(texts)


def test_brand_vocabulary_is_not_a_theme():
    """Words in every text the brand publishes carry no signal about the audience."""
    texts = [f"clarity and reflection and thinking, internal patterns {i}" for i in range(10)]
    themes = _top_words(texts)
    for word in ("clarity", "reflection", "thinking", "internal", "patterns"):
        assert word not in themes, f"{word} appears in every post; it cannot be a finding"


def test_a_word_repeated_inside_one_comment_is_not_a_theme():
    """Frequency alone is not evidence — it has to come from separate people."""
    texts = ["decision decision decision decision decision"] + [
        f"unrelated remark number {i}" for i in range(MIN_COMMENTS_FOR_THEMES)
    ]
    assert "decision" not in _top_words(texts)


def test_a_genuine_theme_still_gets_through():
    """The gate must not be so tight that real signal is discarded."""
    texts = [
        "I keep postponing the decision even though I know the answer",
        "The decision has been made for months, I just have not moved",
        "Every week I revisit the same decision and nothing changes",
        "Unrelated: I liked this post",
        "Another unrelated remark",
        "One more with nothing in common",
    ]
    themes = _top_words(texts)
    assert "decision" in themes, f"real recurring theme was rejected: {themes}"


def test_thresholds_are_meaningful():
    assert MIN_COMMENTS_FOR_THEMES >= 5
    assert MIN_WORD_OCCURRENCES >= 2
    assert MIN_DISTINCT_SOURCES >= 2


# --------------------------------------------------------------------------
# Defect 1 — Threads counted from the wrong file
# --------------------------------------------------------------------------

def test_threads_are_counted_from_the_posts_file(monkeypatch, tmp_path):
    """111 published posts must not be reported as 0."""
    import strategy.strategy_analyzer as sa

    posts = tmp_path / "threads_posts.csv"
    posts.write_text(
        "post_id,generated_text,status\n"
        + "".join(f"p{i},text {i},published\n" for i in range(111))
        + "p999,draft text,draft\n",
        encoding="utf-8",
    )
    # topics.csv deliberately has an empty "Threads Status" column, as in production
    topics = tmp_path / "topics.csv"
    topics.write_text(
        "ID,Topic / Working Title,Status,Pipeline State,Content Pillar,Threads Status\n"
        "1,A topic,Published,Complete,Clarity as Process,\n",
        encoding="utf-8",
    )
    empty = tmp_path / "empty.csv"
    empty.write_text("a\n", encoding="utf-8")

    monkeypatch.setattr(sa, "THREADS_POSTS", posts)
    monkeypatch.setattr(sa, "TOPICS_FILE", topics)
    monkeypatch.setattr(sa, "THREADS_COMMENTS", empty)
    monkeypatch.setattr(sa, "PROMPT_LOG", empty)

    result = sa.analyze()
    assert result["facts"]["channel_counts"]["threads"] == 111
    assert result["facts"]["threads_status_column_count"] == 0


# --------------------------------------------------------------------------
# Downstream — the engine must not rewrite the brand from nothing
# --------------------------------------------------------------------------

@pytest.mark.parametrize("level,should_be_empty", [("weak", True), ("none", True)])
def test_weak_evidence_yields_no_continue_recommendation(level, should_be_empty, monkeypatch, tmp_path):
    import strategy.strategy_analyzer as sa

    comments = tmp_path / "comments.csv"
    comments.write_text("comment_id,post_id,comment_text\n1,p1,it's internal and reduces\n",
                        encoding="utf-8")
    topics = tmp_path / "topics.csv"
    topics.write_text("ID,Topic / Working Title,Status,Pipeline State,Content Pillar\n"
                      "1,A topic,Published,Complete,Clarity as Process\n", encoding="utf-8")
    empty = tmp_path / "empty.csv"
    empty.write_text("a\n", encoding="utf-8")

    monkeypatch.setattr(sa, "THREADS_COMMENTS", comments)
    monkeypatch.setattr(sa, "TOPICS_FILE", topics)
    monkeypatch.setattr(sa, "THREADS_POSTS", empty)
    monkeypatch.setattr(sa, "PROMPT_LOG", empty)

    result = sa.analyze()
    assert result["recommendations"]["continue"] == []
    assert result["facts"]["evidence_level"] != "usable"
    assert "not enough" in result["interpretation"]["evidence_note"].lower()


def test_strongest_channel_is_not_claimed_from_one_comment(monkeypatch, tmp_path):
    import strategy.strategy_analyzer as sa

    comments = tmp_path / "comments.csv"
    comments.write_text("comment_id,post_id,comment_text\n1,p1,a single reply\n", encoding="utf-8")
    topics = tmp_path / "topics.csv"
    topics.write_text("ID,Topic / Working Title,Status,Pipeline State\n1,T,Published,Complete\n",
                      encoding="utf-8")
    empty = tmp_path / "empty.csv"
    empty.write_text("a\n", encoding="utf-8")

    monkeypatch.setattr(sa, "THREADS_COMMENTS", comments)
    monkeypatch.setattr(sa, "TOPICS_FILE", topics)
    monkeypatch.setattr(sa, "THREADS_POSTS", empty)
    monkeypatch.setattr(sa, "PROMPT_LOG", empty)

    channel = sa.analyze()["interpretation"]["strongest_signal_channel"]
    assert channel.lower().startswith("none"), channel


def test_rebuilder_forbids_the_off_brand_register():
    """The engine once proposed 'actionable pathways / empower / roadmap'."""
    source = (ROOT / "strategy" / "strategy_rebuilder.py").read_text(encoding="utf-8")
    for word in ("actionable", "roadmap", "empower", "unlock", "journey"):
        assert word in source, f"the rebuilder prompt no longer forbids '{word}'"
    assert "EVIDENCE IS INSUFFICIENT" in source
    assert "DO NOT propose a new positioning" in source
