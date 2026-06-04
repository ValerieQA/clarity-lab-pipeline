"""AI output parsing and validation helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass


class ContentValidationError(Exception):
    pass


REQUIRED_ARTICLE_SECTIONS = ("title", "instagram", "website", "geo")


def parse_article_sections(raw_text: str) -> dict[str, str]:
    patterns = {
        "title": r"===TITLE===\s*(.*?)(?====|\Z)",
        "instagram": r"===INSTAGRAM===\s*(.*?)(?====|\Z)",
        "website": r"===WEBSITE===\s*(.*?)(?====|\Z)",
        "geo": r"===GEO===\s*(.*?)(?====|\Z)",
    }
    sections: dict[str, str] = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, raw_text or "", re.DOTALL)
        sections[key] = match.group(1).strip() if match else ""
    validate_article_sections(sections)
    return sections


def validate_article_sections(sections: dict[str, str]) -> None:
    missing = [key for key in REQUIRED_ARTICLE_SECTIONS if not sections.get(key, "").strip()]
    if missing:
        raise ContentValidationError(f"Missing required article sections: {', '.join(missing)}")
    if len(sections["title"]) > 180:
        raise ContentValidationError("Article title is unexpectedly long")
    if len(sections["website"].split()) < 120:
        raise ContentValidationError("Website article is too short to publish safely")


def parse_thread_series(raw_text: str) -> list[str]:
    posts = []
    for key in ["POST1", "POST2", "POST3", "POST4"]:
        match = re.search(rf"==={key}===\s*(.*?)(?====|\Z)", raw_text or "", re.DOTALL)
        if match and match.group(1).strip():
            posts.append(match.group(1).strip())
    return posts


def validate_threads_posts(posts: list[str]) -> None:
    if not posts:
        raise ContentValidationError("No Threads posts were generated")
    too_long = [i + 1 for i, post in enumerate(posts) if len(post) > 500]
    if too_long:
        raise ContentValidationError(f"Threads posts exceed 500 characters: {too_long}")
    empty = [i + 1 for i, post in enumerate(posts) if not post.strip()]
    if empty:
        raise ContentValidationError(f"Threads posts are empty: {empty}")
