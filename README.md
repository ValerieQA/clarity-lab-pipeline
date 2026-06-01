# Clarity Lab — Automated Content Pipeline

Automated publishing system: topic → article → image → Wix + Instagram + Facebook

## How it works

1. Picks the next topic with status `Ready` from `topics.csv`
2. Generates article + Instagram post via GPT-4o using `config/prompt.md`
3. Generates image via DALL-E 3
4. Uploads image to Cloudinary
5. Publishes article to Wix Blog
6. Publishes post to Instagram
7. Publishes post to Facebook
8. Marks topic as `Published` in `topics.csv`

Runs automatically: **Monday, Wednesday, Friday at 9:00 AM UTC**
Can also be triggered manually from GitHub Actions tab.

---

## Setup

### 1. Fork / clone this repository

### 2. Add GitHub Secrets

Go to: **Settings → Secrets and variables → Actions → New repository secret**

Add these secrets:

| Secret | Value |
|--------|-------|
| `OPENAI_API_KEY` | Your OpenAI API key |
| `CLOUDINARY_CLOUD_NAME` | Your Cloudinary cloud name |
| `CLOUDINARY_API_KEY` | Your Cloudinary API key |
| `CLOUDINARY_API_SECRET` | Your Cloudinary API secret |
| `WIX_SITE_ID` | `d75ea441-48e8-49c2-b157-b4378a4e102c` |
| `WIX_API_KEY` | Your Wix API key (from Wix dashboard) |
| `IG_USER_ID` | `17841437840015955` |
| `IG_TOKEN` | Your Instagram access token |
| `FB_PAGE_ID` | `1061190690419376` |
| `FB_PAGE_TOKEN` | Your Facebook Page access token |

### 3. Update topics.csv

Add your topics with status `Ready`. The pipeline picks them one by one.

### 4. Update config/prompt.md

Edit the brand voice prompt every 2-3 months based on new research.
This file controls the tone, style, and structure of all articles.

---

## File structure

```
clarity-lab-pipeline/
├── .github/
│   └── workflows/
│       └── schedule.yml     # GitHub Actions schedule
├── config/
│   └── prompt.md            # Brand voice + article prompt (edit this)
├── pipeline.py              # Main pipeline script
├── topics.csv               # Topic bank (updated after each publish)
├── requirements.txt         # Python dependencies
└── README.md
```

---

## Updating the prompt

`config/prompt.md` is the brand voice document. Update it when:
- Strategy changes after quarterly research
- New content pillars are added
- Tone or positioning shifts
- GEO requirements are updated

The pipeline reads this file on every run — no code changes needed.

---

## Adding new topics

Edit `topics.csv` directly in GitHub or locally. Set `Status` to `Ready`.
Topics without a status are also picked up as ready.

---

## Manual run

Go to **Actions tab → Clarity Lab Content Pipeline → Run workflow**

---

## Tokens expiry

Instagram and Facebook tokens expire every ~60 days.
When they expire, regenerate them via Meta Developer Console and update GitHub Secrets.
