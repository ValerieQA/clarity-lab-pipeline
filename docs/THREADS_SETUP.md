# Threads Setup

## Safe defaults

Threads publishing is disabled by default:

```env
ENABLE_THREADS_PUBLISHING=false
THREADS_REQUIRE_APPROVAL=true
THREADS_DAILY_POST_LIMIT=3
THREADS_POSTS_PER_RUN=1
THREADS_SCHEDULE_MODE=spaced
ENABLE_THREADS_COMMENT_COLLECTION=false
ENABLE_THREADS_AUTO_REPLIES=false
ENABLE_PROMPT_EVOLUTION_RECOMMENDATIONS=true
ENABLE_AUTO_PROMPT_UPDATES=false
```

The scheduled Threads workflow runs three spaced checks per day. It creates drafts in `data/threads_posts.csv` and logs skipped publishing unless publishing is explicitly enabled and approval is explicitly bypassed.

## Prompt file

Threads style lives in:

```text
config/THREADS_PROMPT.md
```

Update that file to change Threads voice or format. The code loads it dynamically and does not hardcode writing style rules.

## Draft database

Threads drafts and future discovery-engine fields are stored in:

```text
data/threads_posts.csv
```

Fields include post id, topic, category, opening type, generated text, approval, published status, external Threads id, comments, engagement metrics, and themes.

## Enable publishing later

1. Add `THREADS_ACCESS_TOKEN` and `THREADS_USER_ID` to GitHub Secrets.
2. Run the token check workflow or `python scripts/check_threads_token.py` locally.
3. Review generated drafts in `data/threads_posts.csv`.
4. Manually dispatch the Threads workflow with `enable_threads_publishing=true`.
5. Automatic publishing without review requires both `ENABLE_THREADS_PUBLISHING=true` and `THREADS_REQUIRE_APPROVAL=false` while `DRY_RUN=false`.

Scheduled automatic Threads publishing remains disabled by default. Do not set `THREADS_REQUIRE_APPROVAL=false` unless the current production account is intentionally approved for unattended publishing. Comment collection can be enabled separately with `ENABLE_THREADS_COMMENT_COLLECTION=true`; automatic replies remain disabled and are not implemented. Weekly reports can be generated with `python threads.py --weekly-report` and save to `data/threads_weekly_reports/`. Prompt evolution recommendations are written to `data/prompt_evolution_log.csv` but prompt files are never edited automatically.
