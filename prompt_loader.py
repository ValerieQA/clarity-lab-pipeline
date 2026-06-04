"""Prompt file loading helpers."""

from __future__ import annotations

from pathlib import Path

ARTICLE_PROMPT_PATH = Path("config/prompt.md")
THREADS_PROMPT_PATH = Path("config/THREADS_PROMPT.md")
IMAGE_PROMPT_PATH = Path("config/IMAGE_PROMPT.md")


def load_prompt(path: str | Path) -> str:
    prompt_path = Path(path)
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
    content = prompt_path.read_text(encoding="utf-8").strip()
    if not content:
        raise ValueError(f"Prompt file is empty: {prompt_path}")
    return content
