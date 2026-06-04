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
