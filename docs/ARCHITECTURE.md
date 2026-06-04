# Architecture

## Entry points

| Entry point | Role |
|---|---|
| `pipeline.py` | Main article/image/Wix/Instagram/Facebook pipeline. |
| `threads.py` | Draft-first Threads workflow. Publishing is disabled by default. |
| `stories.py` | Existing Instagram Stories workflow; not refactored in this MVP except shared dependencies remain compatible. |
| `.github/workflows/schedule.yml` | Existing production publishing schedule, preserved. |
| `.github/workflows/threads_workflow.yml` | Safe Threads draft workflow with explicit publishing input. |
| `.github/workflows/dry_run.yml` | Manual dry-run workflow. |
| `.github/workflows/token_check.yml` | Manual/weekly Threads token validation. |

## Shared modules

| Module | Responsibility |
|---|---|
| `runtime_config.py` | Feature flags and Threads config with safe defaults. |
| `structured_logging.py` | JSONL logging to `logs/pipeline.jsonl` with secret redaction. |
| `http_utils.py` | Central retry/backoff/timeout HTTP client. |
| `content_validation.py` | Article section validation and Threads post validation. |
| `publication_state.py` | Platform-specific result tracking and topics CSV compatibility. |
| `meta_tokens.py` | Threads token validation and refresh architecture. |
| `threads_store.py` | Threads draft persistence and lightweight duplicate detection. |
| `prompt_loader.py` | Dynamic prompt file loading. |

## State model

The main pipeline now records platform-specific statuses when updating `topics.csv`:

- `Wix Status`
- `Instagram Status`
- `Facebook Status`
- `Threads Status`
- `Pipeline State`
- `Publication Errors`

Records are only marked fully completed when enabled required platforms succeed. Platform failures are logged and recorded as partial failures where possible.

## Logging

Logs are JSON lines in `logs/pipeline.jsonl` by default. Each event includes timestamp, module, event, severity, platform, status, and safe summaries. Tokens, keys, and secrets are redacted.

## Known limitations

- `stories.py` now uses shared HTTP/dry-run helpers for external calls, but it has not been fully migrated to platform-specific CSV state updates.
- Image prompting is documented by `config/IMAGE_PROMPT.md`, but the current image prompt is still assembled in code to preserve exact production behavior.
- Duplicate detection is lightweight string similarity; semantic duplicate detection is a future improvement.
- Full approval UI and comment collection are not implemented yet.
