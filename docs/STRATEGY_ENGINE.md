# Clarity Lab — Strategy Engine

## Overview

The Strategy Engine extends the content publishing pipeline with autonomous monitoring,
performance analysis, and strategy planning. Publishing continues automatically.
Strategy decisions require human approval.

## The Autonomous Loop

```
Active strategy (current_strategy_state.json)
    ↓
30 content topics (topics.csv)
    ↓
Publishing: Wix / Instagram / Facebook / Threads (schedule.yml)
    ↓
Collect performance and reactions
    ↓
Daily monitoring report (daily_report.yml → reports/daily_report.py)
    ↓
Weekly strategic report (weekly_strategy_report.yml → reports/weekly_strategy_report.py)
    ↓
Topic inventory check (strategy_rebuild_check.yml → strategy/topic_inventory.py)
    ↓
When topics <= 5:
    Strategy diagnosis (strategy/strategy_analyzer.py)
    Research brief (strategy/research_generator.py)
    Proposed strategy + 30 topics (strategy/strategy_rebuilder.py)
    ↓
Email: "Clarity Lab New Strategy Ready for Review"
    ↓
Owner reviews proposed_strategy_YYYY-MM-DD.md
    ↓
Owner approves via approve_strategy.yml (manual trigger)
    ↓
Previous topics.csv archived → new topics.csv activated → next cycle starts
```

## What Runs Automatically

| What | When | Workflow |
|---|---|---|
| Daily report email | Daily 10:00 UTC | `daily_report.yml` |
| Weekly strategy report email | Sundays 11:00 UTC | `weekly_strategy_report.yml` |
| Topic inventory check | Mon/Wed/Fri 10:30 UTC | `strategy_rebuild_check.yml` |
| Strategy rebuild + email | When topics <= 5 | `strategy_rebuild_check.yml` |
| Token health check | Mondays 08:00 UTC | `token_check.yml` |
| Content publishing | Mon/Wed/Fri 09:00 UTC | `schedule.yml` |

## What Requires Manual Action

| What | How |
|---|---|
| Approve new strategy | Run `approve_strategy.yml` with `approve=true` |
| Refresh expired Instagram token | Run `scripts/refresh_instagram_token.py` manually |
| Refresh expired Facebook token | Regenerate in Meta developer portal |
| Force strategy rebuild | Run `strategy_rebuild_check.yml` with `force_rebuild=true` |
| Manual daily report | Run `daily_report.yml` via workflow_dispatch |

## Key Principle

**Nothing in topics.csv is replaced automatically.**
The system proposes. The owner approves.
