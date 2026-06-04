#!/usr/bin/env python3
"""
Encrypt and push a new value to a GitHub Actions repository secret.

Uses the GitHub REST API with a fine-grained PAT stored as GH_TOKEN_WRITER.
The secret value is encrypted locally with the repository's public key
(libsodium sealed box via PyNaCl) before being sent over the wire.

Usage:
    python scripts/update_github_secret.py --secret THREADS_ACCESS_TOKEN --value <new_token>

Environment variables required:
    GH_TOKEN_WRITER   Fine-grained PAT with secrets:write on this repository.
    GH_REPO           Repository in "owner/repo" format (set by GitHub Actions
                      as ${{ github.repository }}).

Exit codes:
    0  Secret updated successfully.
    1  Update failed.
"""

from __future__ import annotations

import argparse
import base64
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests

try:
    from nacl import encoding, public
except ImportError:
    print("ERROR: PyNaCl is required. Run: pip install PyNaCl", file=sys.stderr)
    sys.exit(1)


GITHUB_API = "https://api.github.com"


def _headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _get_repo_public_key(gh_token: str, repo: str) -> tuple[str, str]:
    """Return (key_id, base64_key) for the repository's Actions public key."""
    url = f"{GITHUB_API}/repos/{repo}/actions/secrets/public-key"
    resp = requests.get(url, headers=_headers(gh_token), timeout=15)
    if resp.status_code != 200:
        raise RuntimeError(
            f"Failed to fetch repository public key: HTTP {resp.status_code} — {resp.text[:300]}"
        )
    data = resp.json()
    return data["key_id"], data["key"]


def _encrypt_secret(public_key_b64: str, secret_value: str) -> str:
    """Encrypt secret_value with the repo public key. Returns base64-encoded ciphertext."""
    public_key_bytes = base64.b64decode(public_key_b64)
    sealed_box = public.SealedBox(public.PublicKey(public_key_bytes))
    encrypted = sealed_box.encrypt(secret_value.encode("utf-8"))
    return base64.b64encode(encrypted).decode("utf-8")


def update_github_secret(secret_name: str, secret_value: str) -> None:
    """Encrypt and push *secret_value* to the named GitHub Actions secret."""
    gh_token = os.environ.get("GH_TOKEN_WRITER", "")
    repo = os.environ.get("GH_REPO", "")

    if not gh_token:
        raise RuntimeError("GH_TOKEN_WRITER environment variable is not set.")
    if not repo:
        raise RuntimeError("GH_REPO environment variable is not set (expected 'owner/repo').")

    key_id, public_key_b64 = _get_repo_public_key(gh_token, repo)
    encrypted_value = _encrypt_secret(public_key_b64, secret_value)

    url = f"{GITHUB_API}/repos/{repo}/actions/secrets/{secret_name}"
    payload = {"encrypted_value": encrypted_value, "key_id": key_id}
    resp = requests.put(url, headers=_headers(gh_token), json=payload, timeout=15)

    if resp.status_code not in (201, 204):
        raise RuntimeError(
            f"Failed to update secret '{secret_name}': HTTP {resp.status_code} — {resp.text[:300]}"
        )

    # Do NOT log or print the secret value.
    print(f"GitHub Secret '{secret_name}' updated successfully (repo: {repo}).")


def main() -> int:
    parser = argparse.ArgumentParser(description="Update a GitHub Actions secret via the REST API.")
    parser.add_argument("--secret", required=True, help="Name of the GitHub Secret to update.")
    parser.add_argument("--value", required=True, help="New secret value (never logged).")
    args = parser.parse_args()

    try:
        update_github_secret(args.secret, args.value)
        return 0
    except Exception as exc:
        # Print error to stderr without including the secret value.
        print(f"ERROR updating GitHub Secret '{args.secret}': {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
