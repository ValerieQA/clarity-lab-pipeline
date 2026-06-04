# Environment Variables

## Existing variables preserved

These variables are still used with the same names:

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` | Article, image, story, and Threads draft generation. |
| `CLOUDINARY_CLOUD_NAME` | Cloudinary image upload account. |
| `CLOUDINARY_API_KEY` | Cloudinary API key. |
| `CLOUDINARY_API_SECRET` | Cloudinary API secret. |
| `WIX_SITE_ID` | Wix site identifier. |
| `WIX_API_KEY` | Wix API key. |
| `IG_USER_ID` | Instagram Graph API user id. |
| `IG_TOKEN` | Instagram access token. |
| `FB_PAGE_ID` | Facebook page id. |
| `FB_PAGE_TOKEN` | Facebook page access token. |
| `THREADS_TOKEN` | Backward-compatible Threads token fallback. Prefer `THREADS_ACCESS_TOKEN` for new setup. |

## New safety feature flags

| Variable | Default | Purpose |
|---|---:|---|
| `DRY_RUN` | `false` | When `true`, prepares content and payloads but skips publishing and irreversible uploads. |
| `ENABLE_WIX_PUBLISHING` | `true` | Preserves existing Wix behavior unless disabled. |
| `ENABLE_INSTAGRAM_PUBLISHING` | `true` | Preserves existing Instagram behavior unless disabled. |
| `ENABLE_FACEBOOK_PUBLISHING` | `true` | Preserves existing Facebook behavior unless disabled. |
| `ENABLE_THREADS_PUBLISHING` | `false` | Threads drafts are safe by default; real publishing requires `true`. |
| `THREADS_REQUIRE_APPROVAL` | `true` | Blocks automatic Threads publishing unless explicitly set to `false`. |
| `THREADS_DAILY_POST_LIMIT` | `3` | Maximum individual Threads posts that automated runs may publish per UTC day. |
| `THREADS_POSTS_PER_RUN` | `1` | Maximum individual Threads posts that one automated run may publish. |
| `THREADS_SCHEDULE_MODE` | `spaced` | Documents the intended scheduled posting cadence. |
| `ENABLE_THREADS_COMMENT_COLLECTION` | `false` | Enables collection of replies/comments into `data/threads_comments.csv`. |
| `ENABLE_THREADS_AUTO_REPLIES` | `false` | Reserved for future reply suggestions only; the code does not publish replies automatically. |
| `ENABLE_PROMPT_EVOLUTION_RECOMMENDATIONS` | `true` | Allows weekly reports to write prompt improvement recommendations. |
| `ENABLE_AUTO_PROMPT_UPDATES` | `false` | Prompt files are not edited automatically. |
| `ENABLE_TOKEN_REFRESH` | `false` | Token refresh script refuses to run unless explicitly enabled. |
| `HTTP_MAX_RETRIES` | `3` | Retry limit for external HTTP clients and OpenAI SDK retry configuration. |
| `HTTP_TIMEOUT_SECONDS` | `30` | HTTP timeout for external API requests. |

## New Threads variables

| Variable | Required for publishing | Purpose |
|---|---:|---|
| `THREADS_APP_ID` | No | Reserved for token workflows that need app metadata. |
| `THREADS_APP_SECRET` | No | Reserved for token workflows; never logged. |
| `THREADS_ACCESS_TOKEN` | Yes | Preferred Threads access token. |
| `THREADS_USER_ID` | Yes | Expected Threads user id; token validation checks it. |
| `THREADS_API_VERSION` | No | Defaults to `v1.0`. |


## Threads automation gate

Automated Threads publishing is allowed only when all three conditions are true:

```env
ENABLE_THREADS_PUBLISHING=true
THREADS_REQUIRE_APPROVAL=false
DRY_RUN=false
```

Before publishing, the Threads workflow saves the generated post, checks for duplicates, enforces `THREADS_DAILY_POST_LIMIT` and `THREADS_POSTS_PER_RUN`, validates the Threads token, and records the external Threads id after success. Failed publish attempts update the saved row to `failed` while preserving generated text.

## Threads learning artifacts

| File | Purpose |
|---|---|
| `data/threads_comments.csv` | Stored Threads comments/replies when comment collection is enabled. |
| `data/threads_weekly_reports/` | Weekly JSON learning reports. |
| `data/prompt_evolution_log.csv` | Prompt recommendations with `recommended_not_applied` status. |
