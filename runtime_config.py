"""Runtime configuration helpers for production-safe pipeline feature flags."""

from __future__ import annotations

import os
from dataclasses import dataclass


TRUE_VALUES = {"1", "true", "yes", "y", "on"}
FALSE_VALUES = {"0", "false", "no", "n", "off", ""}


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False
    return default


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class FeatureFlags:
    dry_run: bool = False
    enable_wix_publishing: bool = True
    enable_instagram_publishing: bool = True
    enable_facebook_publishing: bool = True
    enable_threads_publishing: bool = False
    threads_require_approval: bool = False
    threads_daily_post_limit: int = 3
    threads_posts_per_run: int = 1
    threads_schedule_mode: str = "spaced"
    enable_threads_comment_collection: bool = False
    enable_threads_auto_replies: bool = False
    enable_prompt_evolution_recommendations: bool = True
    enable_auto_prompt_updates: bool = False
    enable_token_refresh: bool = False
    http_max_retries: int = 3
    http_timeout_seconds: int = 30

    @classmethod
    def from_env(cls) -> "FeatureFlags":
        return cls(
            dry_run=env_bool("DRY_RUN", False),
            enable_wix_publishing=env_bool("ENABLE_WIX_PUBLISHING", True),
            enable_instagram_publishing=env_bool("ENABLE_INSTAGRAM_PUBLISHING", True),
            enable_facebook_publishing=env_bool("ENABLE_FACEBOOK_PUBLISHING", True),
            enable_threads_publishing=env_bool("ENABLE_THREADS_PUBLISHING", False),
            threads_require_approval=env_bool("THREADS_REQUIRE_APPROVAL", False),
            threads_daily_post_limit=env_int("THREADS_DAILY_POST_LIMIT", 3),
            threads_posts_per_run=env_int("THREADS_POSTS_PER_RUN", 1),
            threads_schedule_mode=os.getenv("THREADS_SCHEDULE_MODE", "spaced"),
            enable_threads_comment_collection=env_bool("ENABLE_THREADS_COMMENT_COLLECTION", False),
            enable_threads_auto_replies=env_bool("ENABLE_THREADS_AUTO_REPLIES", False),
            enable_prompt_evolution_recommendations=env_bool("ENABLE_PROMPT_EVOLUTION_RECOMMENDATIONS", True),
            enable_auto_prompt_updates=env_bool("ENABLE_AUTO_PROMPT_UPDATES", False),
            enable_token_refresh=env_bool("ENABLE_TOKEN_REFRESH", False),
            http_max_retries=env_int("HTTP_MAX_RETRIES", 3),
            http_timeout_seconds=env_int("HTTP_TIMEOUT_SECONDS", 30),
        )


@dataclass(frozen=True)
class ThreadsConfig:
    user_id: str = ""
    access_token: str = ""
    app_id: str = ""
    app_secret: str = ""
    api_version: str = "v1.0"

    @classmethod
    def from_env(cls) -> "ThreadsConfig":
        # Preserve compatibility with the previous THREADS_TOKEN secret while
        # preferring the safer, explicit THREADS_ACCESS_TOKEN name.
        return cls(
            user_id=os.getenv("THREADS_USER_ID", ""),
            access_token=os.getenv("THREADS_ACCESS_TOKEN") or os.getenv("THREADS_TOKEN", ""),
            app_id=os.getenv("THREADS_APP_ID", ""),
            app_secret=os.getenv("THREADS_APP_SECRET", ""),
            api_version=os.getenv("THREADS_API_VERSION", "v1.0"),
        )


@dataclass(frozen=True)
class InstagramConfig:
    user_id: str = ""
    access_token: str = ""
    api_version: str = "v19.0"

    @classmethod
    def from_env(cls) -> "InstagramConfig":
        return cls(
            user_id=os.getenv("IG_USER_ID", ""),
            access_token=os.getenv("IG_TOKEN", ""),
            api_version=os.getenv("IG_API_VERSION", "v19.0"),
        )


@dataclass(frozen=True)
class FacebookConfig:
    page_id: str = ""
    page_token: str = ""
    app_id: str = ""
    app_secret: str = ""
    api_version: str = "v19.0"

    @classmethod
    def from_env(cls) -> "FacebookConfig":
        return cls(
            page_id=os.getenv("FB_PAGE_ID", ""),
            page_token=os.getenv("FB_PAGE_TOKEN", ""),
            app_id=os.getenv("FACEBOOK_APP_ID", ""),
            app_secret=os.getenv("FACEBOOK_APP_SECRET", ""),
            api_version=os.getenv("FB_API_VERSION", "v19.0"),
        )
