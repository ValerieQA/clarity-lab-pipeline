"""Which token each workflow needs, and why.

Pushing needs nothing special: the built-in GITHUB_TOKEN can commit to this
repository when the job declares `permissions: contents: write`, which is how
the Threads workflow has been committing daily all along.

The personal access token is needed for exactly one thing the built-in token
cannot do: writing repository secrets, when a refreshed Meta token has to be
stored back. Keeping it out of every other workflow means a token whose
permissions drift cannot stop publishing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github/workflows"

# The only workflow that writes a repository secret.
PAT_WORKFLOWS = {"token_check.yml"}

PUSHING_WORKFLOWS = [
    "linkedin_workflow.yml",
    "approve_strategy.yml",
    "strategy_rebuild_check.yml",
    "schedule.yml",
    "threads_workflow.yml",
    "retry_channel.yml",
]


def test_only_the_secret_writer_uses_the_personal_access_token():
    users = {
        path.name
        for path in WORKFLOWS.glob("*.yml")
        if "GH_TOKEN_WRITER" in path.read_text(encoding="utf-8")
    }
    assert users == PAT_WORKFLOWS, (
        "a workflow other than the secret writer depends on the PAT; "
        "its permissions can drift and silently stop that workflow"
    )


@pytest.mark.parametrize("name", PUSHING_WORKFLOWS)
def test_pushing_workflows_may_write_contents(name):
    """A job that pushes must say so, or the built-in token is read-only."""
    text = (WORKFLOWS / name).read_text(encoding="utf-8")
    if "git push" not in text:
        pytest.skip(f"{name} does not push")
    assert "contents: write" in text, f"{name} pushes without declaring contents: write"
