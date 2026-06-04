# Threads Setup

## Safe defaults

Threads publishing is disabled by default:

```env
ENABLE_THREADS_PUBLISHING=false
```

The scheduled Threads workflow now creates drafts in `data/threads_posts.csv` and logs skipped publishing unless explicitly enabled.

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

Do not enable scheduled automatic Threads publishing until the approval workflow is operational.
