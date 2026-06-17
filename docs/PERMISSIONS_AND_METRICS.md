# Clarity Lab — Permissions and Metrics

## What Metrics Are Available

### Threads
- **Comments**: collected and stored in `data/threads_comments.csv` by `threads_workflow.yml`
- **Posts**: stored in `data/threads_posts.csv`
- **Likes / Views**: NOT collected — requires `threads_manage_insights` permission (not currently granted)

### Instagram
- **Publish status**: tracked in `topics.csv` (Instagram Status column)
- **Likes / Impressions / Reach**: require `instagram_manage_insights` permission
- **Current status**: permission NOT granted — metrics unavailable

To enable Instagram metrics:
1. Open Meta for Developers → your app → Permissions
2. Add `instagram_manage_insights`
3. Submit for App Review (required for live apps)
4. After approval, metrics will be collected by `metrics/instagram_metrics.py`

### Facebook
- **Publish status**: tracked in `topics.csv` (Facebook Status column)
- **Reactions count**: available via Graph API if `FB_PAGE_TOKEN` is valid
- **Reach / Impressions**: require `pages_read_engagement` permission
- **Current status**: basic reactions may be available; reach requires additional permission

### Wix
- **Publish status**: tracked in `topics.csv` (Wix Status, Published URL columns)
- **Article views / comments**: NOT available via Wix REST API
- **How to check**: Wix Analytics dashboard at https://manage.wix.com/analytics/overview

## Why Reports Say "Data Unavailable"

When a report says:
```
Instagram performance data unavailable because required environment
variables are missing: IG_TOKEN, IG_USER_ID.
```
It means the GitHub secret is not set or has expired. Check `token_check.yml` results.

When a report says:
```
Missing permission: instagram_manage_insights
```
It means the token is valid but the Meta app does not have this permission.
You need to add it in the Meta developer portal and regenerate the token.

## Environment Variables Required

| Variable | Platform | Required for |
|---|---|---|
| `IG_USER_ID` | Instagram | Publishing + metrics |
| `IG_TOKEN` | Instagram | Publishing + metrics |
| `FB_PAGE_ID` | Facebook | Publishing |
| `FB_PAGE_TOKEN` | Facebook | Publishing + basic reactions |
| `THREADS_USER_ID` | Threads | Publishing |
| `THREADS_ACCESS_TOKEN` | Threads | Publishing |
| `WIX_SITE_ID` | Wix | Publishing |
| `WIX_API_KEY` | Wix | Publishing |
| `GMAIL_SENDER` | Email | All reports and alerts |
| `GMAIL_APP_PASSWORD` | Email | All reports and alerts |
| `REPORT_EMAIL_TO` | Email | All reports and alerts |
| `OPENAI_API_KEY` | GPT | Content generation + strategy rebuild |
| `GH_TOKEN_WRITER` | GitHub | Token auto-refresh |
