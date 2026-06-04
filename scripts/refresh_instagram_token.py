#!/usr/bin/env python3
"""
Refresh a long-lived Instagram token when ENABLE_TOKEN_REFRESH=true.

After a successful refresh, the refreshed token is validated and then
written automatically to the GitHub Secret IG_TOKEN via the GitHub REST
API (requires GH_TOKEN_WRITER and GH_REPO env vars).

If GH_TOKEN_WRITER is not set, the script falls back to printing the new
token and asking the developer to update GitHub Secrets manually.
"""

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from http_utils import HttpClient
from meta_tokens import refresh_instagram_token, validate_instagram_token
from runtime_config import FeatureFlags, InstagramConfig
from structured_logging import get_logger


def main() -> int:
    flags = FeatureFlags.from_env()
    if not flags.enable_token_refresh:
        print("Token refresh is disabled. Set ENABLE_TOKEN_REFRESH=true to run this script.")
        return 2

    logger = get_logger("refresh_instagram_token")
    config = InstagramConfig.from_env()
    http = HttpClient.from_flags(flags, logger)

    result = refresh_instagram_token(config, http, logger)
    if not result.success:
        print(f"Instagram token refresh failed: status={result.status}; error={result.error}")
        return 1

    # Validate the new token before updating GitHub Secrets.
    print("Refresh succeeded. Validating new token before updating GitHub Secret...")
    new_config = InstagramConfig(
        user_id=config.user_id,
        access_token=result.access_token,
        api_version=config.api_version,
    )
    validation = validate_instagram_token(new_config, http, logger)
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
            update_github_secret("IG_TOKEN", result.access_token)
            if result.expires_in:
                print(f"New token expires in approximately {result.expires_in} seconds.")
            return 0
        except Exception as exc:
            print(f"ERROR: GitHub Secret update failed: {exc}", file=sys.stderr)
            print("Falling back to manual update instructions.")

    # Manual fallback.
    print("\nInstagram token refresh succeeded.")
    print("Automatic GitHub Secret update is not available in this environment.")
    print("Update GitHub Secret IG_TOKEN manually with the token below.")
    print("Do not commit this value to the repository.\n")
    print(result.access_token)
    if result.expires_in:
        print(f"\nExpires in approximately {result.expires_in} seconds.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
