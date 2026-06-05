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
