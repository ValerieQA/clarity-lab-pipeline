"""The prompt files must keep fitting the code that reads them.

Prompts are rewritten whenever the strategy changes. These tests run the same
checks as scripts/check_prompts.py, which the workflows run before publishing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from check_prompts import (  # noqa: E402
    check_markers,
    check_placeholders,
    check_rotations,
    check_rules,
    run_checks,
)
from prompt_loader import declared_length, load_prompt  # noqa: E402


def test_prompts_and_code_agree():
    problems = run_checks()
    assert problems == [], "\n".join(problems)


@pytest.mark.parametrize("check", [check_rotations, check_placeholders, check_markers, check_rules])
def test_each_check_passes_on_its_own(check):
    assert check() == []


@pytest.mark.parametrize(
    "section,expected",
    [("Visual Journey", 13), ("Subject Families", 9), ("Composition", 7),
     ("Light", 5), ("Accent States", 6)],
)
def test_sections_state_their_own_length(section, expected):
    """The prose carries the count, which is what the checker compares against.

    These numbers may change with the strategy. When one does, the section's
    own sentence changes with it and this test is the reminder.
    """
    assert declared_length(section) == expected


def test_declared_length_reads_both_wordings(tmp_path):
    sample = tmp_path / "sample.md"
    sample.write_text(
        "# Alpha\n\nAdvance one step per published article and wrap after 4.\n\n"
        "0 | a\n1 | b\n2 | c\n3 | d\n\n"
        "# Beta\n\nThe palette changes gradually across three states.\n\n"
        "0 | x\n1 | y\n2 | z\n",
        encoding="utf-8",
    )
    assert declared_length("Alpha", sample) == 4
    assert declared_length("Beta", sample) == 3
    assert declared_length("Gamma", sample) is None


def test_checker_is_the_one_the_workflows_run():
    """A workflow that skips the check leaves the pipeline unguarded."""
    for workflow in ("schedule.yml", "dry_run.yml", "threads_workflow.yml", "stories_workflow.yml"):
        text = load_prompt(ROOT / ".github/workflows" / workflow)
        assert "scripts/check_prompts.py" in text, f"{workflow} publishes without checking prompts"
