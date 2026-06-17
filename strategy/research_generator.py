"""
Research Generator for Clarity Lab Pipeline.

Generates a research brief when topic inventory is low (<=5) or cycle is complete.
Uses GPT to synthesize from existing data (strategy diagnosis, comments, topics).

If OPENAI_API_KEY is unavailable, generates an internal brief from local data only
and clearly marks that external research was not performed.

Outputs:
    data/strategy/research_brief_YYYY-MM-DD.md
    data/strategy/research_brief_YYYY-MM-DD.json
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strategy.strategy_analyzer import analyze as run_analysis

logger = logging.getLogger("research_generator")

STRATEGY_DIR = Path("data/strategy")
TODAY        = date.today()


def _load_latest_diagnosis() -> dict:
    """Load the most recent strategy diagnosis if available."""
    if not STRATEGY_DIR.exists():
        return {}
    files = sorted(STRATEGY_DIR.glob("strategy_diagnosis_*.json"))
    if not files:
        return {}
    try:
        return json.loads(files[-1].read_text(encoding="utf-8"))
    except Exception:
        return {}


def _gpt_research(diagnosis: dict, api_key: str) -> str:
    """Use GPT to generate a research brief from the diagnosis."""
    from openai import OpenAI
    client = OpenAI(api_key=api_key)

    facts   = diagnosis.get("facts", {})
    interp  = diagnosis.get("interpretation", {})
    recs    = diagnosis.get("recommendations", {})
    summary = diagnosis.get("cycle_summary", {})

    prompt = f"""You are a content strategist for Clarity Lab — a psychology and self-understanding brand.

Based on the following content cycle analysis, generate a structured research brief.

## Cycle data
- Topics published: {summary.get('published_topics', 'unknown')}
- Content pillars: {', '.join(facts.get('top_content_pillars', [])) or 'not specified'}
- Comment themes from audience: {', '.join(facts.get('comment_themes', [])) or 'none collected'}
- Failed topics: {', '.join(facts.get('failed_topic_titles', [])) or 'none'}
- What worked (continued): {', '.join(recs.get('continue', [])) or 'unknown'}
- Interpretation: {interp.get('what_strategy_was_tested', 'not specified')}

## Research brief format
Produce a research brief with these sections:
1. Current audience hypothesis (what we believe about the audience based on data)
2. Current positioning hypothesis (how Clarity Lab is positioned)
3. What was tested in this cycle
4. What failed or got no response
5. What worked (based on available signal)
6. 3-5 new content opportunities (specific, not generic)
7. Audience pain points to explore next
8. 3 possible strategic directions for the next cycle

Be specific. Separate facts from hypotheses. Mark anything based on weak or missing data.
Do not invent engagement numbers."""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4,
        max_tokens=2000,
    )
    return response.choices[0].message.content or ""


def _internal_brief(diagnosis: dict) -> str:
    """Generate a minimal internal brief from local data without GPT."""
    facts  = diagnosis.get("facts", {})
    recs   = diagnosis.get("recommendations", {})
    interp = diagnosis.get("interpretation", {})

    lines = [
        "## Internal Research Brief (No External Web Research Performed)",
        "",
        "> External web research was not performed in this run.",
        "> This brief is based entirely on existing pipeline data.",
        "",
        "### Current Audience Hypothesis",
        "Hypothesis based on Threads comment themes: "
        + (f"audience engages with topics around {', '.join(facts.get('comment_themes', [])[:3])}."
           if facts.get("comment_themes") else "insufficient data to form a hypothesis."),
        "",
        "### Current Positioning",
        "Clarity Lab is positioned around psychology, self-understanding, and internal clarity.",
        "Content pillars active this cycle: "
        + (', '.join(facts.get("top_content_pillars", [])) or "not specified."),
        "",
        "### What Was Tested",
        interp.get("what_strategy_was_tested", "Not determinable from current data."),
        "",
        "### What Got No Response",
        "Failed or zero-signal topics: "
        + (', '.join(facts.get("failed_topic_titles", [])[:5]) or "none identified."),
        "",
        "### What Showed Signal",
        "Topics with Threads comment engagement: "
        + (', '.join(interp.get("comment_topics_worth_continuing", [])) or "none identified."),
        "",
        "### Possible Next Strategic Directions",
        "1. Deepen content around recurring comment themes: "
        + (', '.join(facts.get("comment_themes", [])[:3]) or "TBD"),
        "2. Revisit failed topics with a different angle or format.",
        "3. Expand to audience pain points not yet covered in existing topics.",
        "",
        "### Missing Data That Would Improve This Brief",
    ]
    for note in recs.get("missing_data_to_resolve", []):
        lines.append(f"- {note}")
    if not recs.get("missing_data_to_resolve"):
        lines.append("- Instagram and Facebook engagement metrics")
        lines.append("- Wix article view counts")

    return "\n".join(lines)


def generate(trigger: str = "manual") -> dict:
    """
    Generate a research brief. Returns structured dict.
    trigger: 'low_inventory' | 'cycle_complete' | 'manual'
    """
    # Try to load existing diagnosis, or run fresh
    diagnosis = _load_latest_diagnosis()
    if not diagnosis:
        logger.info("No existing diagnosis found — running fresh analysis.")
        diagnosis = run_analysis()

    api_key = os.environ.get("OPENAI_API_KEY", "")
    web_research_performed = False
    brief_text = ""

    if api_key:
        try:
            brief_text = _gpt_research(diagnosis, api_key)
            web_research_performed = False  # GPT synthesizes from local data, not live web
            logger.info("Research brief generated via GPT.")
        except Exception as e:
            logger.warning("GPT brief generation failed (%s), falling back to internal brief.", e)
            brief_text = _internal_brief(diagnosis)
    else:
        logger.info("OPENAI_API_KEY not set — generating internal brief only.")
        brief_text = _internal_brief(diagnosis)

    result = {
        "brief_date": TODAY.isoformat(),
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "trigger": trigger,
        "external_web_research_performed": web_research_performed,
        "gpt_used": bool(api_key and brief_text and "Internal Research Brief" not in brief_text),
        "diagnosis_date": diagnosis.get("analysis_date", "unknown"),
        "remaining_topics": diagnosis.get("cycle_summary", {}).get("remaining_topics", "unknown"),
        "brief": brief_text,
    }

    return result


def to_markdown(brief: dict) -> str:
    lines = [
        f"# Clarity Lab — Research Brief {brief['brief_date']}",
        "",
        f"**Trigger:** {brief['trigger']}  ",
        f"**Based on diagnosis:** {brief['diagnosis_date']}  ",
        f"**Remaining topics:** {brief['remaining_topics']}  ",
    ]
    if not brief["external_web_research_performed"]:
        lines.append("")
        lines.append("> External web research was not performed in this run.")
    lines += ["", "---", "", brief["brief"]]
    return "\n".join(lines)


def save(brief: dict, md: str) -> tuple[Path, Path]:
    STRATEGY_DIR.mkdir(parents=True, exist_ok=True)
    base      = STRATEGY_DIR / f"research_brief_{TODAY.isoformat()}"
    json_path = base.with_suffix(".json")
    md_path   = base.with_suffix(".md")
    json_path.write_text(json.dumps(brief, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(md, encoding="utf-8")
    return json_path, md_path


def run(trigger: str = "manual", send_email: bool = True) -> dict:
    brief = generate(trigger=trigger)
    md    = to_markdown(brief)
    save(brief, md)
    logger.info("Research brief saved for %s (trigger=%s)", TODAY.isoformat(), trigger)

    if send_email:
        from notifications.email_reporter import send_email as _send
        subject = f"Clarity Lab Research Brief — {TODAY.isoformat()} (trigger: {trigger})"
        ok = _send(subject, md)
        if not ok:
            logger.error("Failed to send research brief email.")

    return brief


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--trigger", default="manual",
                        choices=["manual", "low_inventory", "cycle_complete"])
    parser.add_argument("--no-email", action="store_true")
    args = parser.parse_args()
    result = run(trigger=args.trigger, send_email=not args.no_email)
    print(f"Brief date  : {result['brief_date']}")
    print(f"Trigger     : {result['trigger']}")
    print(f"GPT used    : {result['gpt_used']}")
