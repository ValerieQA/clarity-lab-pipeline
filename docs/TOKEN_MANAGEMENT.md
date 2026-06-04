# Token Management

## Platform refresh policy

| Platform  | Auto-refresh       | How                                          |
|-----------|--------------------|----------------------------------------------|
| Threads   | Weekly (automatic) | `token_check.yml` → `token_health_check.py` updates `THREADS_ACCESS_TOKEN` secret via GitHub API |
| Instagram | Manual only        | Run `scripts/refresh_instagram_token.py` locally |
| Facebook  | Never              | Page tokens are non-expiring; regenerate manually in Meta developer portal if needed |

## Weekly token health check

Runs every Monday at 08:00 UTC via `.github/workflows/token_check.yml`.

- **Threads**: validates token, then refreshes and writes new token to `THREADS_ACCESS_TOKEN` GitHub Secret automatically.
- **Instagram**: validates token. If expiry < 14 days, creates a GitHub Issue: *"⏳ Instagram token expiring soon"*.
- **Facebook**: validates token. Warns if a Page token unexpectedly has an expiry date.

If any check fails, a GitHub Issue is created with instructions for manual action.

## Validation only (manual)

```bash
python scripts/token_health_check.py --platform threads
python scripts/token_health_check.py --platform instagram
python scripts/token_health_check.py --platform facebook
```

## Threads manual refresh

```bash
GH_TOKEN_WRITER=<token> GH_REPO=ValerieQA/clarity-lab-pipeline \
  ENABLE_TOKEN_REFRESH=true python scripts/refresh_threads_token.py
```

Requires `GH_TOKEN_WRITER` with `secrets:write` permission. The script validates the new token before writing it to GitHub Secrets. If `GH_TOKEN_WRITER` is not set, the script exits with an error — raw tokens are never printed to stdout.

## Instagram manual refresh

```bash
GH_TOKEN_WRITER=<token> GH_REPO=ValerieQA/clarity-lab-pipeline \
  ENABLE_TOKEN_REFRESH=true python scripts/refresh_instagram_token.py
```

Same requirements as Threads. Run this when you receive the *"Instagram token expiring soon"* GitHub Issue.

## Failure behavior

If validation or refresh fails, scripts print a safe error summary, write structured logs, and exit without modifying existing secrets.
