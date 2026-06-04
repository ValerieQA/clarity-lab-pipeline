#!/usr/bin/env python3
"""Run safe Meta token checks currently supported by this repository."""

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.check_threads_token import main as check_threads


if __name__ == "__main__":
    raise SystemExit(check_threads())
