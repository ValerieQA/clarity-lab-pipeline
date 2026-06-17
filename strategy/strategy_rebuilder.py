"""
Strategy Rebuilder for Clarity Lab Pipeline.

Generates a proposed new strategy and 30 topics based on:
- current strategy diagnosis
- research brief
- existing topics (to avoid exact duplicates)

IMPORTANT:
- Does NOT overwrite topics.csv
- Saves to proposed_strategy_YYYY-MM-DD.md and proposed_topics_YYYY-MM-DD.csv
- Manual approval required before activation (see approve_strategy.yml)
- Sends email: "Clarity Lab New Strategy Ready for Review"

Outputs:
    data/strategy/proposed_strategy_YYYY-MM-DD.md
    data/strategy/proposed_topics_YYYY-MM-DD.csv
"""

from __future__ import annotations

import csv
import json
import logging
import os
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strategy.strategy_analyzer import analyze as run_analysis
from strategy.research_generator import run as run_research

logger = logging.getLogger("strategy_rebuilder")

TOPICS_FILE  = Path(os.environ.get("TOPICS_FILE", "topics.csv"))
STRATEGY_DIR = Path("data/strategy")
TODAY        = date.today()

PROPOSED_TOPICS_FIELDS = [
    "topic_id", "title", "angle", "content_pillar", "audience_pain",
    "channel_priority", "status", "created_at", "strategy_cycle_id",
]


def _existing_titles() -> set[str]:
    """Read current topics.csv to avoid exact title duplication."""
    if not TOPICS_FILE.exists():
        return set()
    with TOPICS_FILE.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return {row.get("Topic / Working Title", "").strip().lower() for row in reader}


def _gpt_strategy(diagnosis: dict, research: dict, api_key: str) -> tuple[str, list[dict]]:
    """Use GPT to generate strategy document and 30 proposed topics."""
    from openai import OpenAI
    client = OpenAI(api_key=api_key)

    facts  = diagnosis.get("facts", {})
    recs   = diagnosis.get("recommendations", {})
    brief  = research.get("brief", "")
    existing = list(_existing_titles())[:20]  # send subset to avoid token bloat

    prompt = f"""You are a content strategist for Clarity Lab — a psychology and self-understanding brand.

## Current cycle data
- Top content pillars: {', '.join(facts.get('top_content_pillars', [])) or 'unknown'}
- Comment themes: {', '.join(facts.get('comment_themes', [])) or 'none'}
- What to continue: {', '.join(recs.get('continue', [])) or 'unknown'}
- What to stop: {', '.join(recs.get('stop_or_test_differently', [])) or 'none'}

## Research brief summary
{brief[:1500]}

## Existing topic titles (do not duplicate)
{chr(10).join(existing[:20])}

## Task
Generate:

1. A new strategy document (200-300 words) with:
   - New positioning hypothesis
   - New audience hypothesis
   - New content pillars (2-3)
   - Recommended content direction
   - What changed from previous cycle
   - Risks

2. Exactly 30 new topic ideas in JSON format:
[
  {{
    "title": "Topic title",
    "angle": "The specific angle or lens for this topic",
    "content_pillar": "Which pillar this belongs to",
    "audience_pain": "The specific audience pain this addresses",
    "channel_priority": "Wix / Instagram / Threads / All"
  }},
  ...
]

Output format:
---STRATEGY---
[strategy document here]
---TOPICS---
[JSON array here]"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5,
        max_tokens=4000,
    )
    content = response.choices[0].message.content or ""

    # Parse strategy and topics
    strategy_text = ""
    topics_json: list[dict] = []

    if "---STRATEGY---" in content and "---TOPICS---" in content:
        parts = content.split("---TOPICS---")
        strategy_text = parts[0].replace("---STRATEGY---", "").strip()
        topics_raw = parts[1].strip()
        # Find JSON array
        start = topics_raw.find("[")
        end   = topics_raw.rfind("]") + 1
        if start >= 0 and end > start:
            try:
                topics_json = json.loads(topics_raw[start:end])
            except json.JSONDecodeError as e:
                logger.warning("Could not parse topics JSON: %s", e)
    else:
        strategy_text = content

    return strategy_text, topics_json


def _fallback_strategy(diagnosis: dict, research: dict) -> tuple[str, list[dict]]:
    """Minimal strategy proposal without GPT."""
    facts  = diagnosis.get("facts", {})
    recs   = diagnosis.get("recommendations", {})
    brief  = research.get("brief", "")

    strategy = (
        "## Proposed Strategy (Generated Without GPT)\n\n"
        "> OPENAI_API_KEY was not available. This is a structural proposal only.\n\n"
        f"**Previous pillars:** {', '.join(facts.get('top_content_pillars', ['unknown']))}\n\n"
        "**Proposed direction:** Continue existing pillars with new angles based on "
        f"audience comment themes: {', '.join(facts.get('comment_themes', ['unknown'])[:3])}.\n\n"
        "**What to continue:** " + ", ".join(recs.get("continue", ["unknown"])) + "\n\n"
        "**What to change:** " + ", ".join(recs.get("stop_or_test_differently", ["unknown"])) + "\n\n"
        "**Risk:** No GPT was used — topics below are placeholder stubs. "
        "Replace or expand before approving this strategy.\n\n"
        "**Research brief excerpt:**\n" + brief[:500]
    )

    # Minimal placeholder topics
    topics = [
        {
            "title": f"[PLACEHOLDER] Topic {i+1} — to be refined",
            "angle": "Define based on research brief",
            "content_pillar": facts.get("top_content_pillars", ["TBD"])[0] if facts.get("top_content_pillars") else "TBD",
            "audience_pain": "Define based on research",
            "channel_priority": "All",
        }
        for i in range(30)
    ]
    return strategy, topics


def build(trigger: str = "manual") -> dict:
    """Build proposed strategy and topics. Returns structured result."""
    diagnosis = run_analysis()
    research  = run_research(trigger=trigger, send_email=False)

    api_key = os.environ.get("OPENAI_API_KEY", "")
    cycle_id = f"CL-{TODAY.strftime('%Y-%m')}-cycle-{TODAY.strftime('%d')}"

    if api_key:
        try:
            strategy_text, raw_topics = _gpt_strategy(diagnosis, research, api_key)
            gpt_used = True
        except Exception as e:
            logger.warning("GPT strategy failed (%s), using fallback.", e)
            strategy_text, raw_topics = _fallback_strategy(diagnosis, research)
            gpt_used = False
    else:
        strategy_text, raw_topics = _fallback_strategy(diagnosis, research)
        gpt_used = False

    # Normalise topics
    proposed_topics = []
    existing_titles = _existing_titles()
    for i, t in enumerate(raw_topics[:30]):
        title = t.get("title", f"Topic {i+1}").strip()
        if title.lower() in existing_titles:
            title = f"{title} (revised)"
        proposed_topics.append({
            "topic_id": f"proposed-{TODAY.isoformat()}-{i+1:02d}",
            "title": title,
            "angle": t.get("angle", ""),
            "content_pillar": t.get("content_pillar", ""),
            "audience_pain": t.get("audience_pain", ""),
            "channel_priority": t.get("channel_priority", "All"),
            "status": "proposed",
            "created_at": TODAY.isoformat(),
            "strategy_cycle_id": cycle_id,
        })

    return {
        "rebuild_date": TODAY.isoformat(),
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "trigger": trigger,
        "gpt_used": gpt_used,
        "cycle_id": cycle_id,
        "strategy_document": strategy_text,
        "proposed_topics": proposed_topics,
        "topics_count": len(proposed_topics),
        "diagnosis_summary": diagnosis.get("cycle_summary", {}),
    }


def save(result: dict) -> tuple[Path, Path, Path]:
    """
    Save proposed strategy and topics files.
    NEVER overwrites topics.csv.
    Returns (strategy_md, topics_csv, metadata_json).
    """
    STRATEGY_DIR.mkdir(parents=True, exist_ok=True)
    d = result["rebuild_date"]

    strategy_md   = STRATEGY_DIR / f"proposed_strategy_{d}.md"
    topics_csv    = STRATEGY_DIR / f"proposed_topics_{d}.csv"
    metadata_json = STRATEGY_DIR / f"proposed_strategy_{d}.json"

    # Strategy markdown
    md_lines = [
        f"# Clarity Lab — Proposed Strategy {d}",
        "",
        f"**Cycle ID:** {result['cycle_id']}  ",
        f"**Generated:** {result['generated_at']}  ",
        f"**Trigger:** {result['trigger']}  ",
        f"**GPT used:** {result['gpt_used']}  ",
        f"**Topics proposed:** {result['topics_count']}  ",
        "",
        "> This is a PROPOSED strategy. It requires manual approval before activation.",
        "> To activate: run `.github/workflows/approve_strategy.yml` with approve=true.",
        "",
        "---",
        "",
        result["strategy_document"],
        "",
        "---",
        "",
        f"## Proposed Topics ({result['topics_count']})",
        "",
        f"See: `{topics_csv.name}`",
    ]
    strategy_md.write_text("\n".join(md_lines), encoding="utf-8")

    # Topics CSV
    with topics_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=PROPOSED_TOPICS_FIELDS)
        writer.writeheader()
        writer.writerows(result["proposed_topics"])

    # Metadata
    metadata = {k: v for k, v in result.items() if k != "proposed_topics"}
    metadata_json.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")

    return strategy_md, topics_csv, metadata_json


def run(trigger: str = "manual", send_email: bool = True) -> dict:
    result = build(trigger=trigger)
    strategy_md, topics_csv, metadata_json = save(result)
    logger.info("Proposed strategy saved: %s (%d topics)", strategy_md, result["topics_count"])

    if send_email:
        from notifications.email_reporter import send_new_strategy
        strategy_md_path = STRATEGY_DIR / f"proposed_strategy_{result['rebuild_date']}.md"
        body = strategy_md_path.read_text(encoding="utf-8") if strategy_md_path.exists() else result["strategy_document"]
        ok = send_new_strategy(body)
        if not ok:
            logger.error("Failed to send new strategy email.")

    return result


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--trigger", default="manual",
                        choices=["manual", "low_inventory", "cycle_complete"])
    parser.add_argument("--no-email", action="store_true")
    args = parser.parse_args()
    result = run(trigger=args.trigger, send_email=not args.no_email)
    print(f"Rebuild date   : {result['rebuild_date']}")
    print(f"Topics proposed: {result['topics_count']}")
    print(f"Cycle ID       : {result['cycle_id']}")
    print(f"GPT used       : {result['gpt_used']}")
