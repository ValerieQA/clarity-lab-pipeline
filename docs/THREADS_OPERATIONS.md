# Threads Operations

## Schedule

| Time (UTC)      | What runs                          |
|-----------------|------------------------------------|
| 01:00 daily     | Publish Threads post               |
| 15:00 daily     | Publish Threads post               |
| 20:00 daily     | Publish Threads post               |
| 06:00 daily     | Collect comments                   |
| 12:00 daily     | Collect comments                   |
| 18:00 daily     | Collect comments                   |
| Monday 07:00    | Weekly learning report             |

After each publish run, comments are also collected automatically if `ENABLE_THREADS_COMMENT_COLLECTION=true` (default: on).

## Where things are stored

| Data                         | Location                                          |
|------------------------------|---------------------------------------------------|
| Published & draft posts      | `data/threads_posts.csv`                          |
| Comments                     | `data/threads_comments.csv`                       |
| Weekly reports               | `data/threads_weekly_reports/threads_weekly_report_YYYY-MM-DD.json` |
| Prompt evolution log         | `data/prompt_evolution_log.csv`                   |

## Post lifecycle

Each post goes through: `draft` → `published` (or `rejected` / `failed`).

- `draft` — generated, saved to CSV, not yet published
- `published` — sent to Threads API; `external_threads_id` is recorded
- `rejected` — duplicate detected before or after generation
- `failed` — Threads API call failed; existing posts are not affected

## How to stop Threads publishing

To pause all scheduled publishing without changing the workflow:

1. Go to **Settings → Variables** in the repository.
2. Add or update: `ENABLE_THREADS_PUBLISHING = false`

The workflow reads this variable at runtime. Scheduled runs will generate drafts but not publish.

To re-enable: set `ENABLE_THREADS_PUBLISHING = true` (or delete the variable — default is `true`).

## How to change daily post limit

In **Settings → Variables**:

```
THREADS_DAILY_POST_LIMIT = 3   # max posts per calendar day
THREADS_POSTS_PER_RUN    = 1   # max posts per single workflow run
```

The system will not publish more than `THREADS_DAILY_POST_LIMIT` posts per day even if you trigger the workflow manually multiple times.

## How to run modes manually

Go to **Actions → Clarity Lab — Threads Pipeline → Run workflow** and select a mode:

| Mode              | What it does                                                 |
|-------------------|--------------------------------------------------------------|
| `publish`         | Generate and publish one post to Threads                     |
| `dry_run`         | Generate post text only, save as draft, do not publish       |
| `collect_comments`| Fetch comments for all published posts, save to CSV          |
| `weekly_report`   | Generate a weekly learning report JSON                       |

## Observing results

- **GitHub Actions summaries** — each run prints a formatted log visible in the Actions tab.
- **`data/threads_posts.csv`** — full history of posts, statuses, and Threads IDs.
- **`data/threads_weekly_reports/`** — JSON reports with top posts, themes, comments, and prompt recommendations.
- **`data/prompt_evolution_log.csv`** — saved recommendations (never applied automatically).

## Prompt evolution

The system analyzes weekly post and comment data and saves recommendations to `data/prompt_evolution_log.csv`. These are **observations only** — the system never edits prompt files automatically (`ENABLE_AUTO_PROMPT_UPDATES=false` is hardcoded).

To apply a recommendation: review `prompt_evolution_log.csv`, edit `config/THREADS_PROMPT.md` manually.

## Safety limits (always on)

- No more than `THREADS_DAILY_POST_LIMIT` posts per day
- No more than `THREADS_POSTS_PER_RUN` posts per run
- Duplicate detection runs before and immediately before the API call
- Token validated before every publish
- Auto-replies: permanently disabled (`ENABLE_THREADS_AUTO_REPLIES=false`)
- Prompt auto-updates: permanently disabled (`ENABLE_AUTO_PROMPT_UPDATES=false`)
