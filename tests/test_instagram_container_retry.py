"""The Instagram container retry loop itself, with HTTP and sleep mocked.

Meta answers 200 with an error payload when it has not fetched the image yet.
Retrying is safe because a container publishes nothing — but only if the loop
retries the right errors, stops at the configured number of attempts, and
never retries a real rejection such as a dead token.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Both modules read their configuration at import time.
FAKE_ENV = {
    "OPENAI_API_KEY": "test", "CLOUDINARY_CLOUD_NAME": "test",
    "CLOUDINARY_API_KEY": "test", "CLOUDINARY_API_SECRET": "test",
    "WIX_SITE_ID": "test", "WIX_API_KEY": "test",
    "IG_USER_ID": "test-ig-user", "IG_TOKEN": "test-ig-token",
    "FB_PAGE_ID": "test", "FB_PAGE_TOKEN": "test",
}

TRANSIENT = {"error": {"message": "Only photo or video can be accepted as media type."}}
REAL_REJECTION = {"error": {"message": "Invalid OAuth access token"}}
MAX_RETRIES = 3


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class FakeHttp:
    """Hands back scripted payloads and remembers every call."""

    def __init__(self, post_payloads, get_payloads=()):
        self._posts = list(post_payloads)
        self._gets = list(get_payloads)
        self.post_urls = []
        self.get_urls = []

    def post(self, url, **kwargs):
        self.post_urls.append(url)
        assert self._posts, f"unexpected POST to {url}"
        return FakeResponse(self._posts.pop(0))

    def get(self, url, **kwargs):
        self.get_urls.append(url)
        assert self._gets, f"unexpected GET to {url}"
        return FakeResponse(self._gets.pop(0))

    @property
    def container_calls(self):
        return [url for url in self.post_urls if url.endswith("/media")]


def _load(module_name, monkeypatch):
    monkeypatch.chdir(ROOT)
    for key, value in FAKE_ENV.items():
        monkeypatch.setenv(key, value)
    sys.modules.pop(module_name, None)
    module = __import__(module_name)
    # FeatureFlags is frozen, so the test swaps the whole object.
    monkeypatch.setattr(module, "FLAGS", replace(
        module.FLAGS,
        http_max_retries=MAX_RETRIES,
        dry_run=False,
        enable_instagram_publishing=True,
    ))
    return module


@pytest.fixture
def waits(monkeypatch):
    """Every sleep the code asks for, without spending the time."""
    recorded = []
    import time

    monkeypatch.setattr(time, "sleep", lambda seconds: recorded.append(seconds))
    return recorded


@pytest.fixture
def pipeline(monkeypatch):
    return _load("pipeline", monkeypatch)


@pytest.fixture
def stories(monkeypatch):
    return _load("stories", monkeypatch)


# --------------------------------------------------------------------------
# Article path — pipeline._create_instagram_container
# --------------------------------------------------------------------------

def test_transient_error_is_retried_and_then_succeeds(pipeline, monkeypatch, waits):
    http = FakeHttp([TRANSIENT, {"id": "container-1"}])
    monkeypatch.setattr(pipeline, "HTTP", http)

    container = pipeline._create_instagram_container("https://img/x.jpg", "caption")

    assert container == {"id": "container-1"}
    assert len(http.container_calls) == 2
    assert waits == [15]


def test_transient_error_gives_up_after_the_configured_attempts(pipeline, monkeypatch, waits):
    http = FakeHttp([TRANSIENT] * MAX_RETRIES)
    monkeypatch.setattr(pipeline, "HTTP", http)

    with pytest.raises(Exception, match="Only photo or video"):
        pipeline._create_instagram_container("https://img/x.jpg", "caption")

    assert len(http.container_calls) == MAX_RETRIES
    assert waits == [15, 30], "backoff should grow, and the last failure must not sleep"


def test_a_real_rejection_is_not_retried(pipeline, monkeypatch, waits):
    http = FakeHttp([REAL_REJECTION])
    monkeypatch.setattr(pipeline, "HTTP", http)

    with pytest.raises(Exception, match="Invalid OAuth access token"):
        pipeline._create_instagram_container("https://img/x.jpg", "caption")

    assert len(http.container_calls) == 1, "a dead token must fail on the first answer"
    assert waits == []


def test_a_clean_first_answer_is_not_retried(pipeline, monkeypatch, waits):
    http = FakeHttp([{"id": "container-1"}])
    monkeypatch.setattr(pipeline, "HTTP", http)

    assert pipeline._create_instagram_container("https://img/x.jpg", "caption") == {"id": "container-1"}
    assert len(http.container_calls) == 1
    assert waits == []


# --------------------------------------------------------------------------
# Stories path — stories.publish_instagram_story
# --------------------------------------------------------------------------

def test_story_transient_error_is_retried_and_then_publishes(stories, monkeypatch, waits):
    http = FakeHttp(
        [TRANSIENT, {"id": "container-1"}, {"id": "story-1"}],
        [{"status_code": "FINISHED"}],
    )
    monkeypatch.setattr(stories, "HTTP", http)

    assert stories.publish_instagram_story("https://img/story.jpg") == "story-1"
    assert len(http.container_calls) == 2
    assert waits == [15]


def test_story_transient_error_gives_up_after_the_configured_attempts(stories, monkeypatch, waits):
    http = FakeHttp([TRANSIENT] * MAX_RETRIES)
    monkeypatch.setattr(stories, "HTTP", http)

    with pytest.raises(Exception, match="Only photo or video"):
        stories.publish_instagram_story("https://img/story.jpg")

    assert len(http.container_calls) == MAX_RETRIES
    assert waits == [15, 30]


def test_story_real_rejection_is_not_retried(stories, monkeypatch, waits):
    http = FakeHttp([REAL_REJECTION])
    monkeypatch.setattr(stories, "HTTP", http)

    with pytest.raises(Exception, match="Invalid OAuth access token"):
        stories.publish_instagram_story("https://img/story.jpg")

    assert len(http.container_calls) == 1
    assert waits == []
