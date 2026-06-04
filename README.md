# Clarity Lab — Automated Content Pipeline

Automated publishing system: topic → article → image → asset handling → Wix + Instagram + Facebook, with safe draft-first Threads support.

## Production safety defaults

The existing production workflow is preserved. New risky behavior is disabled by default:

```env
DRY_RUN=false
ENABLE_WIX_PUBLISHING=true
ENABLE_INSTAGRAM_PUBLISHING=true
ENABLE_FACEBOOK_PUBLISHING=true
ENABLE_THREADS_PUBLISHING=false
THREADS_REQUIRE_APPROVAL=true
THREADS_DAILY_POST_LIMIT=3
THREADS_POSTS_PER_RUN=1
THREADS_SCHEDULE_MODE=spaced
ENABLE_THREADS_COMMENT_COLLECTION=false
ENABLE_THREADS_AUTO_REPLIES=false
ENABLE_PROMPT_EVOLUTION_RECOMMENDATIONS=true
ENABLE_AUTO_PROMPT_UPDATES=false
ENABLE_TOKEN_REFRESH=false
```

When `DRY_RUN=true`, the pipeline may generate content and planned payloads but skips Wix publishing, Instagram publishing, Facebook publishing, Threads publishing, and irreversible asset uploads.

## How the main pipeline works

1. Picks the next topic with status `Ready` from `topics.csv`.
2. Generates article + Instagram post via OpenAI using `config/prompt.md`.
3. Validates the structured AI output before parsing.
4. Generates and brands an image.
5. Uploads the image to Cloudinary unless dry-run mode is enabled.
6. Publishes the article to Wix if enabled.
7. Publishes to Instagram if enabled.
8. Publishes to Facebook if enabled.
9. Records platform-specific publication state in `topics.csv`.

Runs automatically: **Monday, Wednesday, Friday at 9:00 AM UTC**. It can also be triggered manually from the GitHub Actions tab.

## Threads workflow

Threads now uses a separate prompt file:

```text
config/THREADS_PROMPT.md
```

The scheduled Threads workflow is draft-first. It writes generated drafts and future discovery-engine fields to:

```text
data/threads_posts.csv
```

Real Threads publishing only happens when `ENABLE_THREADS_PUBLISHING=true`, `THREADS_REQUIRE_APPROVAL=false`, `DRY_RUN=false`, duplicate checks pass, daily/per-run limits allow it, and token validation succeeds. Generated text is saved before any publish attempt; failures are marked safely without crashing the full pipeline.

## Setup

### Required existing GitHub Secrets

| Secret | Purpose |
|---|---|
| `OPENAI_API_KEY` | OpenAI content/image generation |
| `CLOUDINARY_CLOUD_NAME` | Cloudinary cloud name |
| `CLOUDINARY_API_KEY` | Cloudinary API key |
| `CLOUDINARY_API_SECRET` | Cloudinary API secret |
| `WIX_SITE_ID` | Wix site id |
| `WIX_API_KEY` | Wix API key |
| `IG_USER_ID` | Instagram Graph API user id |
| `IG_TOKEN` | Instagram access token |
| `FB_PAGE_ID` | Facebook page id |
| `FB_PAGE_TOKEN` | Facebook page token |

### Optional/new Threads Secrets

| Secret | Purpose |
|---|---|
| `THREADS_ACCESS_TOKEN` | Preferred Threads token |
| `THREADS_USER_ID` | Expected Threads user id |
| `THREADS_APP_ID` | Reserved for token tooling |
| `THREADS_APP_SECRET` | Reserved for token tooling |

`THREADS_TOKEN` remains supported as a backward-compatible fallback.

## Running locally

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the production pipeline:

```bash
python pipeline.py
```

Run a dry run:

```bash
DRY_RUN=true python pipeline.py
```

Generate a Threads draft:

```bash
python threads.py
```

Validate a Threads token:

```bash
python scripts/check_threads_token.py
```

Collect Threads comments when enabled:

```bash
ENABLE_THREADS_COMMENT_COLLECTION=true python threads.py --collect-comments
```

Generate a weekly Threads learning report:

```bash
python threads.py --weekly-report
```

Refresh a long-lived Threads token manually:

```bash
ENABLE_TOKEN_REFRESH=true python scripts/refresh_threads_token.py
```

## Documentation

- Environment variables: `docs/ENVIRONMENT_VARIABLES.md`
- Token management: `docs/TOKEN_MANAGEMENT.md`
- Threads setup: `docs/THREADS_SETUP.md`
- Architecture: `docs/ARCHITECTURE.md`

## Rollback

To roll back new behavior without reverting code:

1. Keep `ENABLE_THREADS_PUBLISHING=false`.
2. Keep `ENABLE_TOKEN_REFRESH=false`.
3. Set `DRY_RUN=false` for normal production publishing.
4. If needed, disable individual platform flags for safe isolation.
5. Re-run the existing `schedule.yml` workflow after confirming secrets are present.
