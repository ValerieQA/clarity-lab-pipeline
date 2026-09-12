"""Prompt file loading helpers."""

from __future__ import annotations

import re
from pathlib import Path

ARTICLE_PROMPT_PATH   = Path("config/prompt.md")
THREADS_PROMPT_PATH   = Path("config/THREADS_PROMPT.md")
IMAGE_PROMPT_PATH     = Path("config/IMAGE_PROMPT.md")
INSTAGRAM_PROMPT_PATH = Path("config/INSTAGRAM_PROMPT.md")
FACEBOOK_PROMPT_PATH  = Path("config/FACEBOOK_PROMPT.md")
STORIES_PROMPT_PATH   = Path("config/STORIES_PROMPT.md")
LINKEDIN_PROMPT_PATH  = Path("config/LINKEDIN_PROMPT.md")
SCENE_BANK_PATH       = Path("config/SCENE_BANK.md")
HASHTAGS_PATH         = Path("config/HASHTAGS.md")


def load_prompt(path: str | Path) -> str:
    prompt_path = Path(path)
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
    content = prompt_path.read_text(encoding="utf-8").strip()
    if not content:
        raise ValueError(f"Prompt file is empty: {prompt_path}")
    return content


def load_visual_journey() -> list[dict]:
    """Parse the Visual Journey section from IMAGE_PROMPT.md.

    Each line has the format:
        <index> | <name> | mood: <mood> | palette: <palette>

    Returns a list of dicts with keys: index, name, mood, palette.
    """
    content = load_prompt(IMAGE_PROMPT_PATH)

    in_section = False
    entries = []

    for line in content.splitlines():
        stripped = line.strip()

        if stripped == "## Visual Journey":
            in_section = True
            continue

        if in_section:
            # Stop at the next ## section heading
            if stripped.startswith("##"):
                break

            if not stripped or "|" not in stripped:
                continue

            parts = [p.strip() for p in stripped.split("|")]
            if len(parts) < 4:
                continue

            try:
                index = int(parts[0])
            except ValueError:
                continue

            name = parts[1]
            mood_raw = parts[2]
            palette_raw = parts[3]

            mood = re.sub(r"^mood:\s*", "", mood_raw, flags=re.IGNORECASE)
            palette = re.sub(r"^palette:\s*", "", palette_raw, flags=re.IGNORECASE)

            entries.append({
                "index": index,
                "name": name,
                "mood": mood,
                "palette": palette,
            })

    return entries


def load_accent_states() -> list[str]:
    """Parse the Accent States section from IMAGE_PROMPT.md.

    Each line has the format:
        <index> | <accent description>

    Returns a list of accent description strings ordered by index.
    """
    content = load_prompt(IMAGE_PROMPT_PATH)

    in_section = False
    entries = []

    for line in content.splitlines():
        stripped = line.strip()

        if stripped == "## Accent States":
            in_section = True
            continue

        if in_section:
            if stripped.startswith("##"):
                break

            if not stripped or "|" not in stripped:
                continue

            parts = [p.strip() for p in stripped.split("|", 1)]
            if len(parts) < 2:
                continue

            try:
                index = int(parts[0])
            except ValueError:
                continue

            entries.append((index, parts[1]))

    entries.sort(key=lambda x: x[0])
    return [desc for _, desc in entries]


def load_prompt_with_scenes(path: str | Path) -> str:
    """Prompt with the scene bank appended.

    If the scene bank is missing the prompt is returned unchanged, so this is
    always safe to call.
    """
    base = load_prompt(path)
    try:
        return base + "\n\n---\n\n" + load_prompt(SCENE_BANK_PATH)
    except (FileNotFoundError, ValueError):
        return base


def load_hashtags() -> str:
    """Hashtags from config/HASHTAGS.md.

    A line counts as a hashtag when it starts with '#' and contains no spaces,
    which excludes markdown headings ('# Title', '## Section') automatically.
    """
    try:
        content = load_prompt(HASHTAGS_PATH)
    except (FileNotFoundError, ValueError):
        return ""
    tags = [
        line.strip()
        for line in content.splitlines()
        if line.strip().startswith("#") and " " not in line.strip()
    ]
    return " ".join(tags)


def load_indexed_section(section: str, path: str | Path = IMAGE_PROMPT_PATH) -> list[str]:
    """Lines of the form '<index> | <text>' under a '## <section>' heading.

    Returns the texts ordered by index. Everything after the first '|' is
    treated as content, so pipes inside the text are allowed.
    """
    content = load_prompt(path)
    heading = f"## {section}"
    in_section = False
    entries: list[tuple[int, str]] = []

    for line in content.splitlines():
        stripped = line.strip()

        if stripped == heading:
            in_section = True
            continue

        if in_section:
            if stripped.startswith("##"):
                break
            if not stripped or "|" not in stripped:
                continue

            index_part, _, rest = stripped.partition("|")
            try:
                index = int(index_part.strip())
            except ValueError:
                continue
            entries.append((index, rest.strip()))

    entries.sort(key=lambda pair: pair[0])
    return [text for _, text in entries]


def load_subject_families() -> list[str]:
    return load_indexed_section("Subject Families")


def load_compositions() -> list[str]:
    return load_indexed_section("Composition")


def load_light_states() -> list[str]:
    return load_indexed_section("Light")
