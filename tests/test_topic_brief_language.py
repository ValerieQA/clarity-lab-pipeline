"""Topic briefs may arrive in Russian; everything published must be English."""

from pathlib import Path

import pytest

from content_validation import ContentValidationError, validate_article_sections, validate_threads_posts

CHANNEL_PROMPTS = [
    "config/prompt.md",
    "config/THREADS_PROMPT.md",
    "config/INSTAGRAM_PROMPT.md",
    "config/FACEBOOK_PROMPT.md",
    "config/LINKEDIN_PROMPT.md",
    "config/STORIES_PROMPT.md",
]


def _article(**overrides):
    sections = {
        "title": "What the second retelling leaves out",
        "instagram": "She has told the story twice today.",
        "website": "word " * 150,
        "geo": "A reflection on repeated thoughts.",
    }
    sections.update(overrides)
    return sections


@pytest.mark.parametrize("path", CHANNEL_PROMPTS)
def test_every_channel_prompt_treats_topic_as_brief(path):
    text = Path(path).read_text(encoding="utf-8")
    assert "## Topic brief" in text
    assert "write in English from that meaning" in text


def test_english_article_passes():
    validate_article_sections(_article())


@pytest.mark.parametrize("section", ["title", "instagram", "website", "geo"])
def test_cyrillic_in_any_article_section_is_rejected(section):
    with pytest.raises(ContentValidationError, match=f"Cyrillic text: {section}"):
        # Long enough for the website word minimum, short enough for the title limit.
        russian = "Круг размыкается вопросом " * (50 if section == "website" else 2)
        validate_article_sections(_article(**{section: russian}))


def test_cyrillic_threads_post_is_rejected():
    with pytest.raises(ContentValidationError, match="Cyrillic"):
        validate_threads_posts(["Одна и та же мысль по кругу с утра до ночи."])


def test_accented_latin_is_not_mistaken_for_cyrillic():
    validate_threads_posts(["Café, naïve — the “same” thought again."])
