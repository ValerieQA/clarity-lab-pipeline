import tempfile
from pathlib import Path

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


def test_threads_automation_flags_require_explicit_approval_bypass(monkeypatch):
    monkeypatch.setenv("ENABLE_THREADS_PUBLISHING", "true")
    monkeypatch.setenv("THREADS_REQUIRE_APPROVAL", "false")
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("THREADS_DAILY_POST_LIMIT", "3")
    monkeypatch.setenv("THREADS_POSTS_PER_RUN", "1")
    flags = FeatureFlags.from_env()
    assert flags.enable_threads_publishing is True
    assert flags.threads_require_approval is False
    assert flags.threads_daily_post_limit == 3
    assert flags.threads_posts_per_run == 1
    assert flags.enable_threads_comment_collection is False
    assert flags.enable_threads_auto_replies is False
    assert flags.enable_prompt_evolution_recommendations is True
    assert flags.enable_auto_prompt_updates is False


def test_published_thread_count_enforces_daily_limit():
    from datetime import datetime, timezone
    from threads_store import published_thread_count_on, update_post

    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "threads_posts.csv"
        record = draft_record("topic", "A short post", "spark", "spark")
        append_post(record, path)
        update_post(
            record["post_id"],
            {
                "status": "published",
                "external_threads_id": "one,two",
                "published_at": datetime.now(timezone.utc).isoformat(),
            },
            path,
        )
        assert published_thread_count_on(path=path) == 2


def test_weekly_report_logs_prompt_recommendations_without_editing_prompts(tmp_path, monkeypatch):
    from threads_learning import generate_weekly_report

    monkeypatch.chdir(tmp_path)
    Path("data").mkdir()
    flags = FeatureFlags(enable_prompt_evolution_recommendations=True, enable_auto_prompt_updates=True)
    report_path = generate_weekly_report(flags)
    assert report_path.exists()
    assert Path("data/prompt_evolution_log.csv").exists()
    assert not Path("config/THREADS_PROMPT.md").exists()
