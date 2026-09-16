"""Prompt file loading helpers."""

from __future__ import annotations

import re
import tomllib
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
ROTATION_CONTRACT_PATH = Path("config/rotation.toml")

# An entry either sits on one line ("0 | muted terracotta") or opens a block of
# its own ("## 0 | Lived-in interior" followed by prose). Both shapes are in
# IMAGE_PROMPT.md, so every rotation list is read through the same helpers.
_HEADING = re.compile(r"^(#+)\s*(.*)$")
_ENTRY = re.compile(r"^(?:#+\s*)?(\d+)\s*\|\s*(.+)$")


def load_prompt(path: str | Path) -> str:
    prompt_path = Path(path)
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
    content = prompt_path.read_text(encoding="utf-8").strip()
    if not content:
        raise ValueError(f"Prompt file is empty: {prompt_path}")
    return content


def _section_lines(content: str, section: str) -> list[str]:
    """Lines under '# <section>' (any heading depth), up to the next section.

    A deeper heading stays inside the section, so entries written as their own
    sub-headings are kept.
    """
    lines: list[str] = []
    depth = None

    for raw in content.splitlines():
        match = _HEADING.match(raw.strip())

        if depth is None:
            if match and match.group(2).strip().lower() == section.lower():
                depth = len(match.group(1))
            continue

        if match and len(match.group(1)) <= depth:
            break

        lines.append(raw)

    return lines


def _entry_blocks(content: str, section: str) -> list[tuple[int, str, list[str]]]:
    """(index, label, body lines) for every entry of a section, in file order."""
    blocks: list[tuple[int, str, list[str]]] = []

    for raw in _section_lines(content, section):
        stripped = raw.strip()
        match = _ENTRY.match(stripped)
        if match:
            blocks.append((int(match.group(1)), match.group(2).strip(), []))
        elif blocks and stripped:
            blocks[-1][2].append(stripped)

    return blocks


def _first_paragraph(body: list[str]) -> str:
    """The first prose line of an entry body, ignoring bullets and labels."""
    for line in body:
        if line.startswith(("*", "-", "|", ">")) or line.endswith(":"):
            continue
        return line
    return ""


class MissingRotationContract(ValueError):
    """A rotation section has no declared size, so nothing can be verified."""


def load_rotation_contract(path: str | Path = ROTATION_CONTRACT_PATH) -> dict[str, int]:
    """Section name -> required number of entries, from config/rotation.toml.

    The prompt file is prose for the model; this is the part the code reads.
    Keeping the sizes here means a check never has to infer them from a
    sentence someone is free to rewrite.
    """
    contract_path = Path(path)
    if not contract_path.exists():
        raise MissingRotationContract(f"Rotation contract not found: {contract_path}")

    with contract_path.open("rb") as handle:
        data = tomllib.load(handle)

    counts = data.get("counts")
    if not isinstance(counts, dict) or not counts:
        raise MissingRotationContract(f"{contract_path} declares no [counts] section")

    for section, count in counts.items():
        if not isinstance(count, int) or count < 1:
            raise MissingRotationContract(
                f"{contract_path}: '{section}' must declare a positive count, got {count!r}"
            )

    return counts


def declared_length(section: str, path: str | Path = ROTATION_CONTRACT_PATH) -> int:
    """The number of entries a rotation section must hold.

    Raises rather than returning None: an undeclared section would otherwise
    disable the very check that protects it.
    """
    counts = load_rotation_contract(path)
    if section not in counts:
        raise MissingRotationContract(
            f"'{section}' is not declared in {Path(path)}. "
            f"Declared sections: {', '.join(sorted(counts))}."
        )
    return counts[section]


def load_visual_journey() -> list[dict]:
    """Parse the Visual Journey section from IMAGE_PROMPT.md.

    An entry is either one line:
        <index> | <name> | mood: <mood> | palette: <palette>
    or a block:
        <index> | <name>
        mood: <mood>
        palette: <palette>

    Returns a list of dicts with keys: index, name, mood, palette.
    """
    content = load_prompt(IMAGE_PROMPT_PATH)
    entries = []

    for index, label, body in _entry_blocks(content, "Visual Journey"):
        parts = [part.strip() for part in label.split("|")]
        name = parts[0]
        fields = {"mood": "", "palette": ""}

        for candidate in parts[1:] + body:
            for key in fields:
                prefix = f"{key}:"
                if candidate.lower().startswith(prefix) and not fields[key]:
                    fields[key] = candidate[len(prefix):].strip()

        entries.append({
            "index": index,
            "name": name,
            "mood": fields["mood"],
            "palette": fields["palette"],
        })

    entries.sort(key=lambda entry: entry["index"])
    return entries


def load_indexed_section(section: str, path: str | Path = IMAGE_PROMPT_PATH) -> list[str]:
    """Texts of every '<index> | <text>' entry in a section, ordered by index.

    When the entry is a sub-heading with prose under it, the first prose line
    is appended to the heading so the image prompt still receives a
    description rather than a bare label.
    """
    content = load_prompt(path)
    entries: list[tuple[int, str]] = []

    for index, label, body in _entry_blocks(content, section):
        detail = _first_paragraph(body)
        text = f"{label} — {detail}" if detail else label
        entries.append((index, text))

    entries.sort(key=lambda pair: pair[0])
    return [text for _, text in entries]


def load_accent_states() -> list[str]:
    """Accent descriptions from the Accent States section, ordered by index."""
    return load_indexed_section("Accent States")


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


def load_subject_families() -> list[str]:
    return load_indexed_section("Subject Families")


def load_compositions() -> list[str]:
    return load_indexed_section("Composition")


def load_light_states() -> list[str]:
    return load_indexed_section("Light")
