#!/usr/bin/env python3
"""Check that the prompt files still fit the code that reads them.

Prompts get rewritten whenever the strategy changes, and a rewrite can be
perfectly good prose while silently breaking the pipeline: a heading moved one
level, a rotation list turned into sub-headings, a placeholder renamed. That is
how every channel stopped publishing between 13 and 15 September 2026.

Run it before the pipeline runs — `python scripts/check_prompts.py`. It reads
files only, never calls an API, and exits non-zero with a list of what to fix.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prompt_loader import (  # noqa: E402
    ARTICLE_PROMPT_PATH,
    FACEBOOK_PROMPT_PATH,
    HASHTAGS_PATH,
    IMAGE_PROMPT_PATH,
    INSTAGRAM_PROMPT_PATH,
    LINKEDIN_PROMPT_PATH,
    ROTATION_CONTRACT_PATH,
    SCENE_BANK_PATH,
    STORIES_PROMPT_PATH,
    THREADS_PROMPT_PATH,
    MissingRotationContract,
    load_accent_states,
    load_compositions,
    load_hashtags,
    load_light_states,
    load_prompt,
    load_prompt_with_scenes,
    load_rotation_contract,
    load_subject_families,
    load_visual_journey,
)

# Section name -> loader. The names are the headings in IMAGE_PROMPT.md.
ROTATIONS = {
    "Visual Journey": load_visual_journey,
    "Subject Families": load_subject_families,
    "Composition": load_compositions,
    "Light": load_light_states,
    "Accent States": load_accent_states,
}

# Prompt -> the placeholders its call site passes to .format().
SUPPLIED = {
    IMAGE_PROMPT_PATH: {
        "title", "core_observation", "visual_state_name", "visual_state_mood",
        "visual_state_palette", "accent_state", "subject_state",
        "composition_state", "light_state",
    },
    INSTAGRAM_PROMPT_PATH: {
        "title", "core_observation", "audience_question", "content_pillar", "website_url",
    },
    FACEBOOK_PROMPT_PATH: {
        "title", "core_observation", "audience_question", "content_pillar", "website_url",
    },
    LINKEDIN_PROMPT_PATH: {"title", "core_observation", "recent_posts"},
    STORIES_PROMPT_PATH: {"topic", "core_observation", "story_type"},
}

# Prompts whose text reaches the model through a plain string, not .format().
LITERAL_PROMPTS = (ARTICLE_PROMPT_PATH, THREADS_PROMPT_PATH)

# Markers the parsers cut the model's answer on.
REQUIRED_MARKERS = {
    ARTICLE_PROMPT_PATH: ("===TITLE===", "===INSTAGRAM===", "===WEBSITE===", "===GEO==="),
    THREADS_PROMPT_PATH: ("===POST1===",),
}



def check_rotations() -> list[str]:
    """Each rotation list must parse, be complete, and match its declared size."""
    problems = []

    try:
        contract = load_rotation_contract()
    except MissingRotationContract as exc:
        return [f"{exc} Nothing about the rotation can be verified without it."]

    undeclared = set(ROTATIONS) - set(contract)
    if undeclared:
        problems.append(
            f"{ROTATION_CONTRACT_PATH}: no count declared for "
            f"{', '.join(sorted(undeclared))}. Every rotation the code reads must be "
            f"declared here, or its size goes unchecked."
        )

    unknown = set(contract) - set(ROTATIONS)
    if unknown:
        problems.append(
            f"{ROTATION_CONTRACT_PATH}: declares {', '.join(sorted(unknown))}, which the "
            f"code does not read. Either wire the section up or drop it from the contract."
        )

    for section, loader in ROTATIONS.items():
        if section not in contract:
            continue

        entries = loader()

        if not entries:
            problems.append(
                f"{IMAGE_PROMPT_PATH}: section '{section}' parsed as empty. "
                f"Entries are read as '0 | name' lines or '## 0 | name' headings "
                f"under a '# {section}' heading — check the heading and the numbering."
            )
            continue

        if isinstance(entries[0], dict):
            indices = [entry["index"] for entry in entries]
            if indices != list(range(len(entries))):
                problems.append(
                    f"{IMAGE_PROMPT_PATH}: section '{section}' is numbered {indices}, "
                    f"but the rotation needs 0..{len(entries) - 1} with no gaps or repeats."
                )

        if contract[section] != len(entries):
            problems.append(
                f"{IMAGE_PROMPT_PATH}: section '{section}' holds {len(entries)} entries but "
                f"{ROTATION_CONTRACT_PATH} declares {contract[section]}. "
                f"Change the list and the contract in the same edit."
            )

    return problems


def check_placeholders() -> list[str]:
    """Every {placeholder} must be one the calling code actually supplies."""
    problems = []

    for path, supplied in SUPPLIED.items():
        text = load_prompt(path)
        used = set(re.findall(r"\{([a-z_]+)\}", text))
        unknown = used - supplied
        if unknown:
            problems.append(
                f"{path}: uses placeholders nobody supplies: {', '.join(sorted(unknown))}. "
                f"Available here: {', '.join(sorted(supplied))}."
            )
            continue

        try:
            rendered = text.format(**{key: "x" for key in supplied})
        except (IndexError, KeyError, ValueError) as exc:
            problems.append(
                f"{path}: a stray brace breaks formatting ({exc!r}). "
                f"Literal braces must be doubled: {{{{ and }}}}."
            )
            continue

        if "{" in rendered or "}" in rendered:
            problems.append(f"{path}: braces survive formatting — a placeholder is misspelled.")

    for path in LITERAL_PROMPTS:
        text = load_prompt(path)
        stray = set(re.findall(r"\{([a-z_]+)\}", text))
        if stray:
            problems.append(
                f"{path}: contains {{{sorted(stray)[0]}}}, but this prompt is sent as plain text. "
                f"The placeholder will reach the model unfilled."
            )

    return problems


def check_markers() -> list[str]:
    """The answer-splitting markers must be described to the model."""
    problems = []

    for path, markers in REQUIRED_MARKERS.items():
        text = load_prompt(path)
        missing = [marker for marker in markers if marker not in text]
        if missing:
            problems.append(
                f"{path}: does not mention {', '.join(missing)}. "
                f"The parser cuts the answer on those markers and rejects everything else."
            )

    return problems


def check_rules() -> list[str]:
    """Machine contracts only: things the code reads back and depends on.

    Editorial instructions are deliberately not checked here. Whether a prompt
    phrases the language rule one way or another is the owner's business; what
    the code enforces is the output itself, and content_validation rejects
    Cyrillic in an article or a Threads post no matter what the prompt says.
    """
    problems = []

    if not load_hashtags():
        problems.append(f"{HASHTAGS_PATH}: no hashtags parsed. Each one is a line starting with '#'.")

    try:
        load_prompt(SCENE_BANK_PATH)
    except (FileNotFoundError, ValueError):
        problems.append(
            f"{SCENE_BANK_PATH}: missing or empty. Prompts still load, silently, without scenes."
        )

    scened = load_prompt_with_scenes(THREADS_PROMPT_PATH)
    if len(scened) <= len(load_prompt(THREADS_PROMPT_PATH)):
        problems.append(f"{THREADS_PROMPT_PATH}: the scene bank is not being appended.")

    return problems


def run_checks() -> list[str]:
    return check_rotations() + check_placeholders() + check_markers() + check_rules()


def main() -> int:
    problems = run_checks()

    if problems:
        print(f"[PROMPTS] {len(problems)} problem(s) found:\n")
        for problem in problems:
            print(f"  - {problem}\n")
        print("Nothing was published. Fix the files above and run this again.")
        return 1

    counts = ", ".join(f"{section.lower()} {len(loader())}" for section, loader in ROTATIONS.items())
    print(f"[PROMPTS] All checks passed — {counts}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
