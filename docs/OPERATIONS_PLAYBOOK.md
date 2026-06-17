# Clarity Lab — Operations Playbook

## Normal Operations

The pipeline runs automatically. You should receive:
- A daily email every morning with publishing status
- A weekly email on Sunday with strategy overview

No action needed unless an email says "Action Required".

---

## Scenarios and Actions

### "Topic inventory WARNING — 5 topics remaining"

1. Check the strategy rebuild email — a proposed strategy should have arrived.
2. Review `data/strategy/proposed_strategy_YYYY-MM-DD.md`
3. Review `data/strategy/proposed_topics_YYYY-MM-DD.csv`
4. If satisfied: go to GitHub Actions → "Clarity Lab — Approve Strategy" → Run workflow
   - Set `strategy_file` and `topics_file` to the proposed file names
   - Set `approve=true`
5. You will receive a confirmation email when the cycle activates.

### "CRITICAL — No topics remaining, publishing blocked"

Same as above but urgent. Run the approval workflow immediately.
Publishing will resume as soon as the new topics.csv is activated.

### "Token expired — action required"

**Threads token:**
- Run `token_check.yml` — it refreshes automatically if possible
- If refresh fails: go to https://threads.net → Settings → Developer → Regenerate token
- Update `THREADS_ACCESS_TOKEN` in GitHub Secrets

**Instagram token:**
- Run `scripts/refresh_instagram_token.py` locally
- Or regenerate in Meta for Developers portal
- Update `IG_TOKEN` in GitHub Secrets

**Facebook token:**
- Page tokens are long-lived — if expired, regenerate in Meta developer portal
- Update `FB_PAGE_TOKEN` in GitHub Secrets

### "Email reports stopped arriving"

1. Check GitHub Actions → "Clarity Lab — Daily Report" → last run → logs
2. Look for SMTP errors in the "Generate and email daily report" step
3. Verify secrets: `GMAIL_SENDER`, `GMAIL_APP_PASSWORD`, `REPORT_EMAIL_TO`
4. If using Gmail: ensure you're using an App Password (not your account password)
   - Go to Google Account → Security → 2-Step Verification → App passwords

### "Instagram / Facebook publish failing"

1. Check daily report email for error details
2. Check `topics.csv` — Last Error column for the failing topic
3. Manually retry: GitHub Actions → "Retry Channel" → select channel

### "Strategy rebuild email arrived — what to do"

1. Read `data/strategy/proposed_strategy_YYYY-MM-DD.md` (attached or in repo)
2. Check `data/strategy/proposed_topics_YYYY-MM-DD.csv` for the 30 proposed topics
3. Edit the CSV manually if you want to adjust any topics before approving
4. Approve or reject via GitHub Actions → "Clarity Lab — Approve Strategy"
5. **If you reject**: run with `approve=false` — nothing changes, topics.csv stays intact

---

## Manual Triggers

### Force daily report now
GitHub Actions → "Clarity Lab — Daily Report" → Run workflow

### Force weekly report now
GitHub Actions → "Clarity Lab — Weekly Strategy Report" → Run workflow

### Force strategy rebuild now
GitHub Actions → "Clarity Lab — Strategy Rebuild Check" → Run workflow → `force_rebuild=true`

### Run strategy analysis only (no rebuild)
```bash
python3 -m strategy.strategy_analyzer
```
Output: `data/strategy/strategy_diagnosis_YYYY-MM-DD.md`

### Check topic inventory
```bash
python3 -m strategy.topic_inventory
```

### Check pipeline health
```bash
python3 -m strategy.pipeline_health
```

---

## File Structure Reference

```
topics.csv                          ← active topic list (never edited by automation)
data/
  reports/
    daily/   daily_report_YYYY-MM-DD.{json,md}
    weekly/  weekly_report_YYYY-MM-DD.{json,md}
  strategy/
    strategy_diagnosis_YYYY-MM-DD.{json,md}
    research_brief_YYYY-MM-DD.{json,md}
    proposed_strategy_YYYY-MM-DD.md    ← review before approving
    proposed_topics_YYYY-MM-DD.csv     ← review before approving
    current_strategy_state.json        ← updated on approval
    archive/  topics_archived_*.csv    ← previous cycles
  threads_posts.csv
  threads_comments.csv
  threads_weekly_reports/
```
