# Token Management

## Validation

Threads publishing validates the token before any real Threads post is created. Validation calls:

```bash
python scripts/check_threads_token.py
```

The validator checks that:

1. `THREADS_ACCESS_TOKEN` (or fallback `THREADS_TOKEN`) is present.
2. `THREADS_USER_ID` is present.
3. `GET https://graph.threads.net/{THREADS_API_VERSION}/me?fields=id,username` succeeds.
4. The returned id matches `THREADS_USER_ID`.

The token itself is redacted from structured logs.

## Refresh

Token refresh is intentionally disabled by default. To run it manually:

```bash
ENABLE_TOKEN_REFRESH=true python scripts/refresh_threads_token.py
```

The script calls:

```text
GET https://graph.threads.net/refresh_access_token?grant_type=th_refresh_token&access_token=...
```

On success it prints the new token and instructions to update GitHub Secrets manually. It does not modify GitHub Secrets or repository files.

## Failure behavior

If validation or refresh fails, the scripts print a safe error summary, write structured logs, and exit without changing existing secrets.
