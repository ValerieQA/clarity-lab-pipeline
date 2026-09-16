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
from prompt_loader import (  # noqa: E402
    MissingRotationContract,
    declared_length,
    load_prompt,
    load_rotation_contract,
)


def test_prompts_and_code_agree():
    problems = run_checks()
    assert problems == [], "\n".join(problems)


@pytest.mark.parametrize("check", [check_rotations, check_placeholders, check_markers, check_rules])
def test_each_check_passes_on_its_own(check):
    assert check() == []


def test_contract_covers_exactly_the_rotations_the_code_reads():
    """A section the code reads but the contract omits would go unchecked."""
    from check_prompts import ROTATIONS

    assert set(load_rotation_contract()) == set(ROTATIONS)


@pytest.mark.parametrize("section", sorted(load_rotation_contract()))
def test_every_rotation_has_a_declared_count(section):
    assert declared_length(section) >= 1


def test_declared_length_refuses_to_guess():
    """An undeclared section must raise, never return None.

    None would read as "nothing to compare against" and quietly switch off the
    one check that catches a list changing size.
    """
    with pytest.raises(MissingRotationContract):
        declared_length("Weather")


def test_missing_contract_file_is_an_error(tmp_path):
    with pytest.raises(MissingRotationContract):
        load_rotation_contract(tmp_path / "absent.toml")


def test_contract_rejects_a_nonsense_count(tmp_path):
    broken = tmp_path / "rotation.toml"
    broken.write_text('[counts]\n"Light" = 0\n', encoding="utf-8")
    with pytest.raises(MissingRotationContract):
        load_rotation_contract(broken)


def test_checker_is_the_one_the_workflows_run():
    """A workflow that skips the check leaves the pipeline unguarded."""
    for workflow in ("schedule.yml", "dry_run.yml", "threads_workflow.yml", "stories_workflow.yml"):
        text = load_prompt(ROOT / ".github/workflows" / workflow)
        assert "scripts/check_prompts.py" in text, f"{workflow} publishes without checking prompts"
