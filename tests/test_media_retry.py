"""Meta sometimes rejects an image it simply has not fetched yet."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from http_utils import is_transient_media_error  # noqa: E402


@pytest.mark.parametrize("message", [
    "Only photo or video can be accepted as media type.",
    "only photo or video can be accepted as media type",
    "The media could not be fetched from the URI",
    "Media upload has failed, please try again",
])
def test_fetch_failures_are_transient(message):
    assert is_transient_media_error(message)


@pytest.mark.parametrize("message", [
    "Invalid OAuth access token",
    "The aspect ratio is not supported",
    "Application request limit reached",
    "",
])
def test_real_rejections_are_not_retried(message):
    assert not is_transient_media_error(message)


def test_partial_failure_is_still_recorded():
    """The pipeline exits non-zero on a partial failure.

    Wix and Facebook can be published by then, and topics.csv holds that
    record. Without `if: always()` the commit is skipped and the next run
    picks the same topic again and republishes it.
    """
    lines = (ROOT / ".github/workflows/schedule.yml").read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if "Commit updated topics.csv" in line)
    step = "\n".join(lines[start:start + 3])
    assert "if: always()" in step, "a failed run would leave the publish unrecorded"
