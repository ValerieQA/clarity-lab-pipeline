"""Regression tests for the rewritten prompts and the image rotation.

These guard the two things that actually broke before:
  1. images repeating because only the palette rotated
  2. channel prompts existing but never being used
"""

from __future__ import annotations

import re
import sys
from math import gcd
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prompt_loader import (  # noqa: E402
    FACEBOOK_PROMPT_PATH,
    INSTAGRAM_PROMPT_PATH,
    LINKEDIN_PROMPT_PATH,
    THREADS_PROMPT_PATH,
    ARTICLE_PROMPT_PATH,
    load_accent_states,
    load_compositions,
    load_hashtags,
    load_light_states,
    load_prompt,
    load_prompt_with_scenes,
    load_subject_families,
    load_visual_journey,
)

EXPECTED_COUNTS = {
    "visual journey": (load_visual_journey, 13),
    "subject families": (load_subject_families, 9),
    "compositions": (load_compositions, 7),
    "light states": (load_light_states, 5),
    "accent states": (load_accent_states, 6),
}


@pytest.mark.parametrize("name", sorted(EXPECTED_COUNTS))
def test_rotation_lists_have_expected_length(name):
    loader, expected = EXPECTED_COUNTS[name]
    assert len(loader()) == expected, f"{name} changed length; the rotation maths depends on it"


def test_rotation_lengths_are_pairwise_coprime():
    """Coprime lengths are what stop combinations repeating early."""
    lengths = [13, 9, 7, 5]
    for i, a in enumerate(lengths):
        for b in lengths[i + 1:]:
            assert gcd(a, b) == 1, f"{a} and {b} share a factor; images will repeat sooner"


def test_no_repeated_visual_combination_in_a_year():
    """Three articles a week for a year must not reuse a combination."""
    seen = set()
    for i in range(3 * 52):
        seen.add((i % 13, i % 9, i % 7, i % 5))
    assert len(seen) == 3 * 52


def test_image_prompt_formats_with_supplied_placeholders():
    """Every placeholder in IMAGE_PROMPT.md must be one pipeline.py actually passes."""
    from prompt_loader import IMAGE_PROMPT_PATH

    content = load_prompt(IMAGE_PROMPT_PATH)
    supplied = {
        "title", "core_observation", "visual_state_name", "visual_state_mood",
        "visual_state_palette", "accent_state", "subject_state",
        "composition_state", "light_state",
    }
    used = set(re.findall(r"\{([a-z_]+)\}", content))
    assert used <= supplied, f"image prompt uses placeholders nobody supplies: {used - supplied}"

    journey = load_visual_journey()[0]
    rendered = content.format(
        title="t", core_observation="c",
        visual_state_name=journey["name"], visual_state_mood=journey["mood"],
        visual_state_palette=journey["palette"], accent_state=load_accent_states()[0],
        subject_state=load_subject_families()[0], composition_state=load_compositions()[0],
        light_state=load_light_states()[0],
    )
    assert "{" not in rendered and "}" not in rendered


@pytest.mark.parametrize("path", [INSTAGRAM_PROMPT_PATH, FACEBOOK_PROMPT_PATH])
def test_channel_prompts_format_with_scene_bank(path):
    """The prompts pipeline.py now calls must render with the scene bank attached."""
    rendered = load_prompt_with_scenes(path).format(
        title="t", core_observation="c", audience_question="q",
        content_pillar="p", website_url="https://example.com",
    )
    assert "{" not in rendered and "}" not in rendered
    assert "Scene" in rendered or "scene" in rendered


def test_linkedin_prompt_formats():
    rendered = load_prompt(LINKEDIN_PROMPT_PATH).format(
        title="t", core_observation="c", recent_posts="none yet",
    )
    assert "{" not in rendered and "}" not in rendered
    assert "===LINKEDIN_EN===" in rendered and "===CASE===" in rendered


def test_scene_bank_is_attached_to_threads_prompt():
    plain = load_prompt(THREADS_PROMPT_PATH)
    with_scenes = load_prompt_with_scenes(THREADS_PROMPT_PATH)
    assert len(with_scenes) > len(plain)
    assert "S01" in with_scenes


def test_hashtags_exclude_markdown_headings():
    tags = load_hashtags().split()
    assert tags, "no hashtags parsed"
    assert all(" " not in t for t in tags)
    assert not any(t.startswith("##") for t in tags)
    assert "#humandesign" not in tags, "the retired hashtag came back"
    assert "#mindfulness" not in tags, "the retired hashtag came back"


@pytest.mark.parametrize("path", [
    ARTICLE_PROMPT_PATH, INSTAGRAM_PROMPT_PATH, FACEBOOK_PROMPT_PATH,
    THREADS_PROMPT_PATH, LINKEDIN_PROMPT_PATH,
])
def test_prompts_forbid_the_esoteric_mechanic(path):
    """Human Design and Gene Keys stay off the storefront, in every prompt."""
    text = load_prompt(path).lower()
    assert "never mention human design" in text or "do not mention" in text, (
        f"{path} does not forbid the mechanic explicitly"
    )


@pytest.mark.parametrize("path", [
    ARTICLE_PROMPT_PATH, INSTAGRAM_PROMPT_PATH, FACEBOOK_PROMPT_PATH, THREADS_PROMPT_PATH,
])
def test_prompts_ban_the_machine_antithesis(path):
    """The 'not X, but Y' shape was in 39% of old posts. Every prompt must forbid it."""
    text = load_prompt(path).lower()
    assert "not x, but y" in text, f"{path} does not ban the antithesis construction"


def test_article_prompt_keeps_required_output_sections():
    """content_validation.parse_article_sections depends on all four markers."""
    text = load_prompt(ARTICLE_PROMPT_PATH)
    for marker in ("===TITLE===", "===INSTAGRAM===", "===WEBSITE===", "===GEO==="):
        assert marker in text, f"{marker} missing — the parser would reject every article"


@pytest.mark.parametrize("path", [
    ARTICLE_PROMPT_PATH, INSTAGRAM_PROMPT_PATH, FACEBOOK_PROMPT_PATH, THREADS_PROMPT_PATH,
])
def test_banned_openings_rule_is_about_the_plural(path):
    """'Someone asks...' is the required opening; 'Some people...' is the banned one.

    The first version of this rule listed the bare token 'Some', which reads as a
    ban on 'Someone' — the exact opening the Scene Rule asks for.
    """
    text = load_prompt(path)
    assert "The rule is about the plural" in text, f"{path} still bans the bare token"
    assert "Someone" in text, f"{path} does not show that 'Someone' is a correct opening"
