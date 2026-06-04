#!/usr/bin/env python3
"""Refresh a long-lived Threads token when ENABLE_TOKEN_REFRESH=true."""

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from http_utils import HttpClient
from meta_tokens import refresh_threads_token
from runtime_config import FeatureFlags, ThreadsConfig
from structured_logging import get_logger


def main() -> int:
    flags = FeatureFlags.from_env()
    if not flags.enable_token_refresh:
        print("Token refresh is disabled. Set ENABLE_TOKEN_REFRESH=true to run this script.")
        return 2

    logger = get_logger("refresh_threads_token")
    result = refresh_threads_token(ThreadsConfig.from_env(), HttpClient.from_flags(flags, logger), logger)
    if not result.success:
        print(f"Threads token refresh failed safely: status={result.status}; error={result.error}")
        return 1

    print("Threads token refresh succeeded.")
    print("Update your GitHub Actions secret THREADS_ACCESS_TOKEN with the token below.")
    print("Do not commit this value to the repository.")
    print(result.access_token)
    if result.expires_in:
        print(f"Expires in approximately {result.expires_in} seconds.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
