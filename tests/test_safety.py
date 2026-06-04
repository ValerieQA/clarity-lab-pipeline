import tempfile
from pathlib import Path
import pytest

from content_validation import ContentValidationError, parse_article_sections, validate_threads_posts
from runtime_config import FeatureFlags, ThreadsConfig
from threads_store import append_post, draft_record, find_duplicate
from meta_tokens import validate_threads_token
from http_utils import HttpClient


def test_feature_flag_defaults_are_safe(monkeypatch):
    for name in ["DRY_RUN", "ENABLE_THREADS_PUBLISHING", "ENABLE_TOKEN_REFRESH"]:
        monkeypatch.delenv(name, raising=False)
    flags = FeatureFlags.from_env()
    assert flags.dry_run is False
    assert flags.enable_threads_publishing is False
    assert flags.enable_token_refresh is False
    assert flags.enable_wix_publishing is True
    assert flags.enable_instagram_publishing is True
    assert flags.enable_facebook_publishing is True


def test_threads_missing_token_fails_safely():
    result = validate_threads_token(ThreadsConfig(user_id="123", access_token=""), HttpClient(max_retries=1, timeout=1))
    assert result.valid is False
    assert result.status == "missing_token"


def test_malformed_article_output_rejected():
    try:
        parse_article_sections("===TITLE===\nOnly title")
    except ContentValidationError as exc:
        assert "Missing required article sections" in str(exc)
    else:
        raise AssertionError("Malformed output should fail")


def test_threads_length_validation_rejects_long_post():
    try:
        validate_threads_posts(["x" * 501])
    except ContentValidationError:
        pass
    else:
        raise AssertionError("Long Threads post should fail")


def test_duplicate_detection_blocks_obvious_repeat():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "threads_posts.csv"
        record = draft_record("topic", "This is a repeatable reflection about clarity.", "spark", "spark")
        append_post(record, path)
        duplicate = find_duplicate("This is a repeatable reflection about clarity.", path=path)
        assert duplicate.is_duplicate is True


def test_dry_run_publish_helpers_do_not_call_http(monkeypatch):
    pytest.importorskip("openai")
    required_env = {
        "OPENAI_API_KEY": "test",
        "CLOUDINARY_CLOUD_NAME": "test",
        "CLOUDINARY_API_KEY": "test",
        "CLOUDINARY_API_SECRET": "test",
        "WIX_SITE_ID": "test",
        "WIX_API_KEY": "test",
        "IG_USER_ID": "123",
        "IG_TOKEN": "test",
        "FB_PAGE_ID": "456",
        "FB_PAGE_TOKEN": "test",
    }
    for key, value in required_env.items():
        monkeypatch.setenv(key, value)
    import importlib
    import pipeline

    pipeline = importlib.reload(pipeline)
    pipeline.FLAGS = FeatureFlags(dry_run=True)

    def fail_post(*args, **kwargs):
        raise AssertionError("HTTP should not be called in dry-run publish helpers")

    monkeypatch.setattr(pipeline.HTTP, "post", fail_post)
    assert pipeline.publish_to_instagram("caption", "image") == "dry-run-instagram-id"
    assert pipeline.publish_to_facebook("message", "image") == "dry-run-facebook-id"
    assert pipeline.publish_to_wix("Title", "Website body", "image").startswith("dry-run://wix/post/")
