"""Threads comments, weekly learning reports, and prompt evolution logs."""

from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from http_utils import HttpClient, response_json_or_raise
from runtime_config import FeatureFlags, ThreadsConfig
from threads_store import read_posts

COMMENTS_DB = Path("data/threads_comments.csv")
COMMENTS_FIELDS = ["comment_id", "post_id", "author", "comment_text", "created_at", "collected_at", "weight"]
REPORT_DIR = Path("data/threads_weekly_reports")
PROMPT_EVOLUTION_LOG = Path("data/prompt_evolution_log.csv")
PROMPT_EVOLUTION_FIELDS = ["created_at", "source", "recommendation", "rationale", "status"]
STOPWORDS = {
    "about", "after", "again", "because", "before", "being", "between", "clarity", "could", "from", "have",
    "into", "more", "most", "that", "the", "their", "there", "these", "this", "threads", "through", "with", "would",
}


def ensure_comments_store(path: Path = COMMENTS_DB) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with path.open("w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=COMMENTS_FIELDS).writeheader()


def read_comments(path: Path = COMMENTS_DB) -> list[dict[str, str]]:
    ensure_comments_store(path)
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def append_comments(comments: list[dict[str, str]], path: Path = COMMENTS_DB) -> int:
    ensure_comments_store(path)
    existing_ids = {row.get("comment_id") for row in read_comments(path)}
    new_rows = [row for row in comments if row.get("comment_id") and row.get("comment_id") not in existing_ids]
    if not new_rows:
        return 0
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COMMENTS_FIELDS)
        for row in new_rows:
            writer.writerow({field: row.get(field, "") for field in COMMENTS_FIELDS})
    return len(new_rows)


def collect_threads_comments(config: ThreadsConfig, http: HttpClient, flags: FeatureFlags, path: Path = COMMENTS_DB) -> int:
    """Collect replies for published posts when explicitly enabled.

    This intentionally stores comments only. It never sends replies, even if
    ENABLE_THREADS_AUTO_REPLIES is accidentally set true in the environment.
    """
    if not flags.enable_threads_comment_collection:
        return 0
    if not config.access_token:
        return 0

    collected_at = datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, str]] = []
    for post in read_posts():
        if post.get("status") != "published":
            continue
        for external_id in [item.strip() for item in post.get("external_threads_id", "").split(",") if item.strip()]:
            try:
                response = http.get(
                    f"https://graph.threads.net/{config.api_version}/{external_id}/replies",
                    platform="threads",
                    params={"fields": "id,text,username,timestamp", "access_token": config.access_token},
                )
                data = response_json_or_raise(response, "THREADS COMMENT COLLECTION")
            except Exception:
                continue
            for item in data.get("data", []):
                text = str(item.get("text", ""))
                rows.append(
                    {
                        "comment_id": str(item.get("id", "")),
                        "post_id": external_id,
                        "author": str(item.get("username", "")),
                        "comment_text": text,
                        "created_at": str(item.get("timestamp", "")),
                        "collected_at": collected_at,
                        "weight": str(comment_weight(text)),
                    }
                )
    return append_comments(rows, path)


def comment_weight(text: str) -> int:
    length_score = min(3, max(1, len(text.strip()) // 80 + 1))
    tension_bonus = 1 if any(word in text.lower() for word in ("but", "stuck", "hard", "confused", "tension", "afraid")) else 0
    return length_score + tension_bonus


def generate_weekly_report(flags: FeatureFlags, report_dir: Path = REPORT_DIR) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=7)
    posts = [_row for _row in read_posts() if _within(_row.get("published_at", ""), start, now)]
    comments = [_row for _row in read_comments() if _within(_row.get("created_at") or _row.get("collected_at", ""), start, now)]

    themes = _themes([p.get("generated_text", "") for p in posts] + [c.get("comment_text", "") for c in comments])
    strongest_comments = sorted(comments, key=lambda row: int(row.get("weight") or 0), reverse=True)[:5]
    best_posts = _best_posts(posts)[:5]
    tensions = [word for word, _count in themes if word in {"stuck", "confused", "afraid", "tension", "pressure", "doubt", "overwhelmed"}]
    article_ideas = [f"Explore the hidden pattern behind {word}" for word, _count in themes[:5]] or ["Reflect on the strongest audience question from this week"]
    recommendations = _prompt_recommendations(themes, strongest_comments) if flags.enable_prompt_evolution_recommendations else []

    if flags.enable_prompt_evolution_recommendations:
        save_prompt_recommendations(recommendations)
    # Guardrail: recommendations are logged only; prompt files are never edited here.
    if flags.enable_auto_prompt_updates:
        save_prompt_recommendations([
            {
                "recommendation": "Automatic prompt updates were requested but are disabled by policy.",
                "rationale": "ENABLE_AUTO_PROMPT_UPDATES must not edit prompt files automatically.",
            }
        ])

    report = {
        "generated_at": now.isoformat(),
        "window_start": start.isoformat(),
        "published_posts_count": len(posts),
        "best_performing_posts": best_posts,
        "most_common_themes": themes[:10],
        "strongest_comments": strongest_comments,
        "repeated_tensions": tensions,
        "suggested_article_ideas": article_ideas,
        "suggested_prompt_evolution_recommendations": recommendations,
    }
    path = report_dir / f"threads_weekly_report_{now.date().isoformat()}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def save_prompt_recommendations(recommendations: list[dict[str, str]], path: Path = PROMPT_EVOLUTION_LOG) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    if not exists:
        with path.open("w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=PROMPT_EVOLUTION_FIELDS).writeheader()
    now = datetime.now(timezone.utc).isoformat()
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=PROMPT_EVOLUTION_FIELDS)
        for row in recommendations:
            writer.writerow(
                {
                    "created_at": now,
                    "source": "threads_weekly_report",
                    "recommendation": row.get("recommendation", ""),
                    "rationale": row.get("rationale", ""),
                    "status": "recommended_not_applied",
                }
            )
    return len(recommendations)


def _within(raw: str, start: datetime, end: datetime) -> bool:
    if not raw:
        return False
    try:
        when = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return start <= when <= end


def _themes(texts: list[str]) -> list[tuple[str, int]]:
    counter: Counter[str] = Counter()
    for text in texts:
        for word in "".join(ch.lower() if ch.isalnum() else " " for ch in text).split():
            if len(word) > 4 and word not in STOPWORDS:
                counter[word] += 1
    return counter.most_common(20)


def _best_posts(posts: list[dict[str, str]]) -> list[dict[str, Any]]:
    scored = []
    for post in posts:
        metrics = {}
        try:
            metrics = json.loads(post.get("engagement_metrics") or "{}")
        except json.JSONDecodeError:
            pass
        score = sum(int(metrics.get(key, 0) or 0) for key in ("likes", "replies", "reposts", "quotes"))
        scored.append({"post_id": post.get("post_id", ""), "external_threads_id": post.get("external_threads_id", ""), "score": score, "text_preview": post.get("generated_text", "")[:240]})
    return sorted(scored, key=lambda row: row["score"], reverse=True)


def _prompt_recommendations(themes: list[tuple[str, int]], comments: list[dict[str, str]]) -> list[dict[str, str]]:
    recommendations: list[dict[str, str]] = []
    if themes:
        theme = themes[0][0]
        recommendations.append({"recommendation": f"Test one Threads opening that names the audience tension around '{theme}'.", "rationale": "This theme appeared most often in recent posts/comments."})
    if comments:
        recommendations.append({"recommendation": "Add one prompt instruction to invite grounded audience reflection, not advice-giving.", "rationale": "The strongest comments tend to contain personal tension and may benefit from reflective follow-up prompts."})
    if not recommendations:
        recommendations.append({"recommendation": "Keep current Threads prompt unchanged until more comments are collected.", "rationale": "Insufficient recent engagement signal for safe prompt evolution."})
    return recommendations
