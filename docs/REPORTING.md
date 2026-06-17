# Clarity Lab — Reporting

## Email Reports

All reports are sent to the email configured in `REPORT_EMAIL_TO` secret.

| Report | Subject | When |
|---|---|---|
| Daily | `Clarity Lab Daily Report — YYYY-MM-DD` | Daily 10:00 UTC |
| Weekly | `Clarity Lab Weekly Strategy Report — Week of YYYY-MM-DD` | Sundays 11:00 UTC |
| Critical alert | `Clarity Lab Alert — Action Required` | On critical pipeline event |
| Token alert | `Clarity Lab Alert — Token / Permission Issue` | On token failure |
| Cycle complete | `Clarity Lab Strategy Cycle Complete` | On cycle completion |
| New strategy | `Clarity Lab New Strategy Ready for Review` | When strategy rebuild runs |

## Daily Report Contents

- Pipeline health status (overall: healthy / warning / critical / blocked)
- Topic inventory (remaining count, days left, status)
- What was published today (per channel)
- What failed and what is in the retry queue
- Channel breakdown: Wix / Instagram / Facebook / Threads
- Action items (token warnings, missing permissions)

## Weekly Strategy Report Contents

- Content published this week (per channel)
- Threads comment themes (from collected comments)
- Best-performing Threads posts (by comment count)
- Strategy signals (what to continue, what failed)
- Data availability notes (explains why Instagram/Facebook/Wix data may be unavailable)
- Operational issues (token expiry, missing secrets)
- Topic inventory status

## Where Reports Are Stored

```
data/reports/daily/   daily_report_YYYY-MM-DD.json + .md
data/reports/weekly/  weekly_report_YYYY-MM-DD.json + .md
data/strategy/        strategy_diagnosis_*.json + .md
                      research_brief_*.json + .md
                      proposed_strategy_*.md
                      proposed_topics_*.csv
```

## Manually Triggering Reports

```bash
# Daily report (no email)
SEND_EMAIL_ALERTS=false python3 -m reports.daily_report

# Weekly report (no email)
SEND_EMAIL_ALERTS=false python3 -m reports.weekly_strategy_report

# Via GitHub Actions UI
# Go to Actions → Clarity Lab — Daily Report → Run workflow
```

## If Email Fails

Email failures are logged to the GitHub Actions run log.
The workflow does NOT fail when email fails (reporting failure must not block publishing).
Check the run log under the "Generate and email" step for SMTP errors.

If email consistently fails, verify:
1. `GMAIL_SENDER` secret is set (e.g. `kovalchuk25@gmail.com`)
2. `GMAIL_APP_PASSWORD` secret is a valid Gmail App Password (not your regular password)
3. `REPORT_EMAIL_TO` secret is set
4. Gmail "Less secure app access" is not required — App Passwords work with 2FA enabled
