"""Platform-specific publication state tracking for topics.csv compatibility."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PipelineStatus(str, Enum):
    DRAFT = "draft"
    GENERATED = "generated"
    CONTENT_VALIDATED = "content_validated"
    IMAGE_GENERATED = "image_generated"
    ASSET_UPLOADED = "asset_uploaded"
    WIX_PUBLISHED = "wix_published"
    INSTAGRAM_PUBLISHED = "instagram_published"
    FACEBOOK_PUBLISHED = "facebook_published"
    THREADS_PUBLISHED = "threads_published"
    COMPLETED = "completed"
    PARTIAL_FAILURE = "partial_failure"
    FAILED = "failed"


@dataclass
class PlatformResult:
    platform: str
    enabled: bool
    status: str = "skipped"
    external_id: str = ""
    url: str = ""
    error: str = ""


@dataclass
class PublicationState:
    topic_id: str = ""
    status: PipelineStatus = PipelineStatus.DRAFT
    platform_results: dict[str, PlatformResult] = field(default_factory=dict)

    def set_platform(self, platform: str, enabled: bool, status: str, external_id: str = "", url: str = "", error: str = "") -> None:
        self.platform_results[platform] = PlatformResult(platform, enabled, status, external_id, url, error)

    def finalize(self) -> PipelineStatus:
        enabled_results = [r for r in self.platform_results.values() if r.enabled]
        failures = [r for r in enabled_results if r.status == "failed"]
        pending = [r for r in enabled_results if r.status not in {"published", "skipped"}]
        if failures and any(r.status == "published" for r in enabled_results):
            self.status = PipelineStatus.PARTIAL_FAILURE
        elif failures or pending:
            self.status = PipelineStatus.FAILED
        else:
            self.status = PipelineStatus.COMPLETED
        return self.status


def ensure_topic_state_fields(rows: list[dict[str, Any]]) -> list[str]:
    fieldnames = list(rows[0].keys()) if rows else []
    for field in [
        "Pipeline State",
        "Wix Status",
        "Instagram Status",
        "Facebook Status",
        "Threads Status",
        "Threads External ID",
        "Publication Errors",
        "IG Caption",
        "FB Message",
        "Instagram Post ID",
        "Facebook Post ID",
        "Story ID",
        "Last Error",
        "Last Failed Channel",
        "Retry Available",
    ]:
        if field not in fieldnames:
            fieldnames.append(field)
        for row in rows:
            if field not in row:
                row[field] = ""
    return fieldnames


def write_topics(path: str, rows: list[dict[str, Any]]) -> None:
    fieldnames = ensure_topic_state_fields(rows)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
