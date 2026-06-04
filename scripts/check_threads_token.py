#!/usr/bin/env python3
"""Validate THREADS_ACCESS_TOKEN without printing the token."""

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from http_utils import HttpClient
from meta_tokens import validate_threads_token
from runtime_config import FeatureFlags, ThreadsConfig
from structured_logging import get_logger


def main() -> int:
    logger = get_logger("check_threads_token")
    flags = FeatureFlags.from_env()
    result = validate_threads_token(ThreadsConfig.from_env(), HttpClient.from_flags(flags, logger), logger)
    if result.valid:
        print(f"Threads token valid for user_id={result.user_id} username={result.username}")
        return 0
    print(f"Threads token invalid: status={result.status}; error={result.error}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
