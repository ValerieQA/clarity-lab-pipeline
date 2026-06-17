"""
Strategy Analyzer for Clarity Lab Pipeline.

Analyzes the current or last content cycle using all available local data:
topics.csv, daily/weekly reports, Threads posts/comments, prompt evolution log.

Separates facts (what happened) from interpretation (what it might mean).
Clearly labels weak-signal conclusions.
Does not invent performance data.

Outputs:
    data/strategy/strategy_diagnosis_YYYY-MM-DD.md
    data/strategy/strategy_diagnosis_YYYY-MM-DD.json
"""

from __future__ import annotations

import csv
import json
import logging
import os
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strategy.topic_inventory import load_inventory

logger = logging.getLogger("strategy_analyzer")

TOPICS_FILE      = Path(os.environ.get("TOPICS_FILE", "topics.csv"))
THREADS_POSTS    = Path("data/threads_posts.csv")
THREADS_COMMENTS = Path("data/threads_comments.csv")
PROMPT_LOG       = Path("data/prompt_evolution_log.csv")
REPORTS_DIR      = Path("data/reports")
STRATEGY_DIR     = Path("data/strategy")
TODAY            = date.today()

STOPWORDS = {
    "the", "a", "an", "is", "it", "in", "of", "to", "and", "that", "this",
    "for", "i", "you", "we", "are", "was", "be", "have", "not", "with", "as",
    "at", "by", "from", "or", "but", "they", "their", "its", "which", "more",
    "clarity", "about", "into", "some", "been", "when", "who", "what",
}


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _top_words(texts: list[str], n: int = 8) -> list[str]:
    words: Counter = Counter()
    for text in texts:
        for word in text.lower().split():
            word = word.strip(".,!?;:\"'()-")
            if len(word) > 3 and word not in STOPWORDS:
                words[word] += 1
    return [w for w, _ in words.most_common(n)]


def _load_prompt_evolution() -> list[dict]:
    return _read_csv(PROMPT_LOG)


def _load_weekly_reports() -> list[dict]:
    """Load all weekly JSON reports."""
    reports_dir = Path("data/threads_weekly_reports")
    results = []
    if reports_dir.exists():
        for p in sorted(reports_dir.glob("threads_weekly_report_*.json")):
            try:
                results.append(json.loads(p.read_text(encoding="utf-8")))
            except Exception:
                pass
    return results


def analyze() -> dict:
    """
    Run full strategy analysis. Returns structured diagnosis dict.
    """
    topics   = _read_csv(TOPICS_FILE)
    posts    = _read_csv(THREADS_POSTS)
    comments = _read_csv(THREADS_COMMENTS)
    prom_log = _load_prompt_evolution()
    w_reports = _load_weekly_reports()
    inventory = load_inventory(TOPICS_FILE)

    # --- Facts: topic breakdown ---
    published = [t for t in topics if t.get("Pipeline State", "").lower() in ("completed",)
                 or t.get("Status", "").lower() == "published"]
    failed    = [t for t in topics if t.get("Pipeline State", "").lower() in ("failed", "partial_failure")]
    remaining = [t for t in topics if t.get("Status", "").lower() in ("ready", "") and
                 t.get("Pipeline State", "").lower() not in ("completed", "failed", "partial_failure")]

    # --- Facts: content pillars ---
    pillar_counter: Counter = Counter()
    for t in published:
        pillar = t.get("Content Pillar", "").strip()
        if pillar:
            pillar_counter[pillar] += 1
    top_pillars = [p for p, _ in pillar_counter.most_common(3)]

    # --- Facts: Threads comment signal ---
    comment_texts = [c.get("comment_text", "") for c in comments if c.get("comment_text")]
    comment_themes = _top_words(comment_texts)
    posts_with_comments = len({c.get("post_id") for c in comments if c.get("post_id")})

    # --- Facts: published topic titles ---
    published_titles = [t.get("Topic / Working Title", "") for t in published]
    failed_titles    = [t.get("Topic / Working Title", "") for t in failed]

    # --- Facts: channel availability ---
    wix_published = [t for t in published if t.get("Wix Status", "").lower() == "published"]
    ig_published  = [t for t in published if t.get("Instagram Status", "").lower() == "published"]
    fb_published  = [t for t in published if t.get("Facebook Status", "").lower() == "published"]
    th_published  = [t for t in published if t.get("Threads Status", "").lower() == "published"]

    # --- Prompt evolution ---
    recent_prompt_recs = [
        p.get("recommendation", "") for p in prom_log[-3:]
        if p.get("recommendation")
    ]

    # --- Weak-signal labels ---
    data_quality_notes: list[str] = []
    if len(comments) < 5:
        data_quality_notes.append(
            "WEAK SIGNAL: fewer than 5 Threads comments collected — comment theme analysis is not statistically meaningful."
        )
    if not ig_published:
        data_quality_notes.append(
            "NO DATA: Instagram engagement metrics not available (no published posts recorded or missing instagram_manage_insights permission)."
        )
    if not fb_published:
        data_quality_notes.append(
            "NO DATA: Facebook engagement metrics not available."
        )
    if not wix_published:
        data_quality_notes.append(
            "NO DATA: No Wix articles recorded as published. Wix analytics not collected via API."
        )
    if posts_with_comments == 0 and len(posts) > 0:
        data_quality_notes.append(
            "NOTICE: Threads posts exist but no comments were collected. Comments collector may need to run."
        )

    # --- Strategy interpretation (based on facts only) ---
    # Best performing: posts that have most comments
    post_comment_counts: Counter = Counter()
    for c in comments:
        pid = c.get("post_id", "")
        if pid:
            post_comment_counts[pid] += 1

    best_post_ids = [pid for pid, _ in post_comment_counts.most_common(3)]
    best_posts = [p for p in posts if p.get("post_id") in best_post_ids]

    return {
        "analysis_date": TODAY.isoformat(),
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "cycle_summary": {
            "total_topics": inventory["total_topics"],
            "published_topics": len(published),
            "failed_topics": len(failed),
            "remaining_topics": len(remaining),
            "inventory_status": inventory["status"],
        },
        "facts": {
            "published_topic_titles": published_titles,
            "failed_topic_titles": failed_titles,
            "top_content_pillars": top_pillars,
            "threads_posts_count": len(posts),
            "threads_comments_count": len(comments),
            "posts_with_comments": posts_with_comments,
            "comment_themes": comment_themes,
            "channel_counts": {
                "wix": len(wix_published),
                "instagram": len(ig_published),
                "facebook": len(fb_published),
                "threads": len(th_published),
            },
        },
        "interpretation": {
            "what_strategy_was_tested": (
                f"Content across {len(set(top_pillars))} pillar(s): {', '.join(top_pillars)}."
                if top_pillars else "Strategy pillars not determinable from available data."
            ),
            "strongest_signal_channel": (
                "Threads" if len(comments) > 0 else "No channel engagement data available."
            ),
            "comment_topics_worth_continuing": comment_themes[:3],
            "best_performing_posts": [
                p.get("text_preview", p.get("topic_id", ""))[:80] for p in best_posts
            ],
            "what_is_unclear_due_to_missing_data": data_quality_notes,
            "recent_prompt_evolution": recent_prompt_recs,
        },
        "recommendations": {
            "continue": comment_themes[:3] if comment_themes else [],
            "stop_or_test_differently": failed_titles[:3] if failed_titles else [],
            "missing_data_to_resolve": [
                n for n in data_quality_notes if n.startswith(("NO DATA", "WEAK SIGNAL"))
            ],
            "next_steps": [
                "Collect Instagram and Facebook post IDs to enable metric collection.",
                "Ensure Threads comments are collected before running strategy analysis.",
                "Review Wix dashboard for article view counts (not available via API).",
            ] if data_quality_notes else [
                "Data is sufficient. Proceed to strategy rebuilder for next cycle planning."
            ],
        },
    }


def to_markdown(diagnosis: dict) -> str:
    d    = diagnosis["analysis_date"]
    cyc  = diagnosis["cycle_summary"]
    facts = diagnosis["facts"]
    interp = diagnosis["interpretation"]
    recs   = diagnosis["recommendations"]

    lines = [
        f"# Clarity Lab — Strategy Diagnosis {d}",
        "",
        "## Cycle Summary",
        "",
        f"- Total topics in cycle: {cyc['total_topics']}",
        f"- Published: {cyc['published_topics']}",
        f"- Failed: {cyc['failed_topics']}",
        f"- Remaining: {cyc['remaining_topics']}",
        f"- Inventory status: **{cyc['inventory_status'].upper()}**",
        "",
        "---",
        "",
        "## Facts (What Happened)",
        "",
        f"**Top content pillars:** {', '.join(facts['top_content_pillars']) or 'N/A'}",
        "",
        "**Published topics:**",
    ]
    for t in facts["published_topic_titles"]:
        lines.append(f"- {t}")
    if not facts["published_topic_titles"]:
        lines.append("- None recorded")

    lines += [
        "",
        "**Failed topics:**",
    ]
    for t in facts["failed_topic_titles"]:
        lines.append(f"- {t}")
    if not facts["failed_topic_titles"]:
        lines.append("- None")

    lines += [
        "",
        "**Channel publish counts:**",
        f"- Wix: {facts['channel_counts']['wix']}",
        f"- Instagram: {facts['channel_counts']['instagram']}",
        f"- Facebook: {facts['channel_counts']['facebook']}",
        f"- Threads: {facts['channel_counts']['threads']}",
        "",
        f"**Threads comments collected:** {facts['threads_comments_count']} "
        f"(across {facts['posts_with_comments']} posts)",
    ]
    if facts["comment_themes"]:
        lines.append(f"**Comment themes:** {', '.join(facts['comment_themes'])}")

    lines += [
        "",
        "---",
        "",
        "## Interpretation",
        "",
        f"**Strategy tested:** {interp['what_strategy_was_tested']}",
        f"**Strongest signal channel:** {interp['strongest_signal_channel']}",
        "",
    ]
    if interp["best_performing_posts"]:
        lines.append("**Best-performing post excerpts (by comment count):**")
        for p in interp["best_performing_posts"]:
            lines.append(f'- "{p}…"')
        lines.append("")

    if interp["what_is_unclear_due_to_missing_data"]:
        lines.append("**Data quality notes:**")
        for note in interp["what_is_unclear_due_to_missing_data"]:
            lines.append(f"> {note}")
        lines.append("")

    lines += [
        "---",
        "",
        "## Recommendations",
        "",
        "**Continue:**",
    ]
    for r in recs["continue"] or ["Insufficient data to recommend."]:
        lines.append(f"- {r}")

    lines += [
        "",
        "**Stop or test differently:**",
    ]
    for r in recs["stop_or_test_differently"] or ["No clear candidates identified."]:
        lines.append(f"- {r}")

    lines += [
        "",
        "**To improve data quality:**",
    ]
    for s in recs["next_steps"]:
        lines.append(f"- {s}")

    return "\n".join(lines)


def save(diagnosis: dict, md: str) -> tuple[Path, Path]:
    STRATEGY_DIR.mkdir(parents=True, exist_ok=True)
    base      = STRATEGY_DIR / f"strategy_diagnosis_{TODAY.isoformat()}"
    json_path = base.with_suffix(".json")
    md_path   = base.with_suffix(".md")
    json_path.write_text(json.dumps(diagnosis, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(md, encoding="utf-8")
    return json_path, md_path


def run() -> dict:
    diagnosis = analyze()
    md = to_markdown(diagnosis)
    json_path, md_path = save(diagnosis, md)
    logger.info("Strategy diagnosis saved: %s", json_path)
    return diagnosis


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    d = run()
    print(f"Analysis date  : {d['analysis_date']}")
    print(f"Published      : {d['cycle_summary']['published_topics']}")
    print(f"Inventory      : {d['cycle_summary']['inventory_status']}")
    print(f"Comment themes : {', '.join(d['facts']['comment_themes']) or 'none'}")
