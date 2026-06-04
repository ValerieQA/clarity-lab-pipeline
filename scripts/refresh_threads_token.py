#!/usr/bin/env python3
"""
Refresh a long-lived Threads token when ENABLE_TOKEN_REFRESH=true.

After a successful refresh, the refreshed token is validated and then
written automatically to the GitHub Secret THREADS_ACCESS_TOKEN via
the GitHub REST API (requires GH_TOKEN_WRITER and GH_REPO env vars).

If GH_TOKEN_WRITER is not set, the script falls back to printing the new
token and asking the developer to update GitHub Secrets manually.
"""

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from http_utils import HttpClient
from meta_tokens import refresh_threads_token, validate_threads_token
from runtime_config import FeatureFlags, ThreadsConfig
from structured_logging import get_logger


def main() -> int:
    flags = FeatureFlags.from_env()
    if not flags.enable_token_refresh:
        print("Token refresh is disabled. Set ENABLE_TOKEN_REFRESH=true to run this script.")
        return 2

    logger = get_logger("refresh_threads_token")
    config = ThreadsConfig.from_env()
    http = HttpClient.from_flags(flags, logger)

    result = refresh_threads_token(config, http, logger)
    if not result.success:
        print(f"Threads token refresh failed: status={result.status}; error={result.error}")
        return 1

    # Validate the new token before updating GitHub Secrets.
    print("Refresh succeeded. Validating new token before updating GitHub Secret...")
    new_config = ThreadsConfig(
        user_id=config.user_id,
        access_token=result.access_token,
        app_id=config.app_id,
        app_secret=config.app_secret,
        api_version=config.api_version,
    )
    validation = validate_threads_token(new_config, http, logger)
    if not validation.valid:
        print(
            f"Refreshed token failed validation: {validation.status} — {validation.error}\n"
            "GitHub Secret NOT updated. Existing token preserved."
        )
        return 1

    import os
    gh_token_writer = os.environ.get("GH_TOKEN_WRITER", "")
    gh_repo = os.environ.get("GH_REPO", "")

    if gh_token_writer and gh_repo:
        try:
            from scripts.update_github_secret import update_github_secret
            update_github_secret("THREADS_ACCESS_TOKEN", result.access_token)
            if result.expires_in:
                print(f"New token expires in approximately {result.expires_in} seconds.")
            return 0
        except Exception as exc:
            print(f"ERROR: GitHub Secret update failed: {exc}", file=sys.stderr)
            return 1

    # GH_TOKEN_WRITER not available — cannot update secret automatically.
    print("\nERROR: GH_TOKEN_WRITER is not set. Cannot update GitHub Secret automatically.")
    print("Set GH_TOKEN_WRITER and GH_REPO environment variables and re-run this script.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
