"""Prove — or disprove — that Wix preserves an explicitly supplied blog post slug.

Read-only in phase A. Phase B publishes and then deletes, and is opt-in.

## Why this exists

The social-publishing-engine design for a Wix Blog publisher
(ValerieQA/social-publishing-engine#68) needs one provider behaviour that the
documentation does not state: whether an explicitly supplied ``seoSlug`` survives
unchanged through publish, **including on collision**.

That question is load-bearing rather than academic. If the slug is preserved, then
``GET /blog/v3/posts/slugs/{slug}`` is a durable recovery key: after a publish call whose
outcome we could not read, a later run can ask "is this already published?" and get a real
answer, without storing any provider id. If Wix silently rewrites the slug — a ``-1``
suffix on collision, say — that lookup misses, and the engine has to fall back to blocking
every ambiguous publish for a human to resolve by hand.

This pipeline's own ``publish_to_wix`` already assumes the answer. It never sends
``seoSlug``, then constructs the returned URL as
``https://www.inneros.online/post/{slugified title}`` and reports it as published without
ever fetching it. That URL has never been verified against the provider. If this probe
shows Wix derives a different slug, some of those recorded URLs are wrong.

## What it does

**Phase A — drafts only, nothing publicly visible.** Create two drafts requesting the
*same* explicit slug, read both back, and compare byte for byte.

**Phase B — publish, look up by slug, delete.** Only run when phase A shows the slug
surviving into the draft; otherwise the answer is already no and publishing proves nothing
that is worth a live post for.

Everything created is deleted at the end, including on failure.

Nothing here prints a credential. The API key is read from the environment and passed only
in the ``Authorization`` header.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

WIX_API = "https://www.wixapis.com"
SITE_ID = os.environ["WIX_SITE_ID"]
API_KEY = os.environ["WIX_API_KEY"]

#: This site's blog member, taken from the value ``pipeline.py`` already publishes with.
#: A member GUID, not a credential.
MEMBER_ID = os.environ.get("WIX_MEMBER_ID", "4d7e0085-753e-4aee-b7c6-ed66431fd9c6")

RUN_PHASE_B = os.environ.get("RUN_PHASE_B", "false").lower() == "true"

#: Deliberately awkward, and obviously a test to anyone who sees it.
STAMP = time.strftime("%Y%m%d-%H%M%S")
REQUESTED_SLUG = f"spe-slug-probe-{STAMP}"
TITLE = "SPE system test - slug probe (safe to ignore)"

HEADERS = {
    "Authorization": API_KEY,
    "wix-site-id": SITE_ID,
    "Content-Type": "application/json",
}


def call(method: str, path: str, body: Any = None) -> tuple[int, Any]:
    """One Graph call. Returns the status and the decoded body, never raising on 4xx/5xx."""
    url = f"{WIX_API}{path}"
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, headers=HEADERS, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return exc.code, {"raw": raw.decode("utf-8", "replace")[:400]}


def paragraph(text: str) -> dict[str, Any]:
    """The smallest valid Ricos document: one paragraph holding one text node."""
    return {
        "nodes": [
            {
                "type": "PARAGRAPH",
                "id": "probe1",
                "nodes": [
                    {
                        "type": "TEXT",
                        "id": "",
                        "nodes": [],
                        "textData": {"text": text, "decorations": []},
                    }
                ],
            }
        ]
    }


def create_draft(label: str) -> tuple[str | None, str | None, dict[str, Any]]:
    """Create a draft asking for REQUESTED_SLUG. Returns (draft id, slug it came back with)."""
    status, payload = call(
        "POST",
        "/blog/v3/draft-posts",
        {
            "draftPost": {
                "title": f"{TITLE} {label}",
                "excerpt": "Automated contract probe. Deleted immediately.",
                "seoSlug": REQUESTED_SLUG,
                "memberId": MEMBER_ID,
                "richContent": paragraph(
                    "Automated system test for the social-publishing-engine Wix design. "
                    "This post is deleted as soon as the check finishes."
                ),
            }
        },
    )
    draft = payload.get("draftPost") or {}
    print(f"  create {label}: HTTP {status}")
    if status >= 400:
        print(f"  error: {json.dumps(payload)[:400]}")
        return None, None, payload
    return draft.get("id"), draft.get("seoSlug"), payload


def read_draft(draft_id: str) -> tuple[int, str | None]:
    status, payload = call("GET", f"/blog/v3/draft-posts/{draft_id}")
    return status, (payload.get("draftPost") or {}).get("seoSlug")


def main() -> int:
    print(f"Requested slug: {REQUESTED_SLUG!r}")
    print(f"Site: {SITE_ID[:8]}… (truncated)")
    findings: dict[str, Any] = {"requested_slug": REQUESTED_SLUG}
    drafts: list[str] = []
    posts: list[str] = []

    try:
        # -- Phase A: two drafts asking for the same slug ---------------------------
        print("\n== PHASE A - drafts only, nothing published ==")

        id_a, slug_a, _ = create_draft("A")
        if not id_a:
            findings["phase_a"] = "create failed"
            return 1
        drafts.append(id_a)
        status, read_a = read_draft(id_a)
        print(f"  draft A: returned seoSlug={slug_a!r}, read back={read_a!r} (HTTP {status})")

        id_b, slug_b, _ = create_draft("B")
        if id_b:
            drafts.append(id_b)
            status, read_b = read_draft(id_b)
            print(f"  draft B: returned seoSlug={slug_b!r}, read back={read_b!r} (HTTP {status})")
        else:
            read_b = None
            print("  draft B: refused at create - a collision on the draft itself")

        preserved = read_a == REQUESTED_SLUG
        findings["phase_a"] = {
            "draft_a_slug": read_a,
            "draft_b_slug": read_b,
            "slug_preserved_on_draft": preserved,
            "second_draft_accepted": id_b is not None,
            "drafts_share_slug": bool(read_b) and read_a == read_b,
        }
        print(f"\n  -> explicit seoSlug preserved on the draft: {preserved}")

        if not preserved:
            print("  -> phase B skipped: the slug is already not preserved, so publishing")
            print("     it would prove nothing that is worth a live post.")
            findings["phase_b"] = "skipped - slug not preserved at draft stage"
            return 0

        if not RUN_PHASE_B:
            print("\n  phase B not requested (RUN_PHASE_B != true). Stopping after drafts.")
            findings["phase_b"] = "not requested"
            return 0

        # -- Phase B: publish, look up by slug, delete -------------------------------
        print("\n== PHASE B - publishing, briefly ==")

        status, payload = call("POST", f"/blog/v3/draft-posts/{id_a}/publish")
        post_a = payload.get("postId")
        print(f"  publish A: HTTP {status}, postId={post_a}")
        if post_a:
            posts.append(post_a)

        encoded = urllib.parse.quote(REQUESTED_SLUG, safe="")
        status, payload = call("GET", f"/blog/v3/posts/slugs/{encoded}")
        found = payload.get("post") or {}
        print(f"  lookup by slug: HTTP {status}, post id={found.get('id')}, slug={found.get('slug')!r}")
        findings["phase_b"] = {
            "post_a_id": post_a,
            "lookup_status": status,
            "lookup_matched_post_a": found.get("id") == post_a,
            "published_slug": found.get("slug"),
            "slug_survived_publish": found.get("slug") == REQUESTED_SLUG,
            "provider_url": (found.get("url") or {}).get("path"),
        }

        if id_b:
            status, payload = call("POST", f"/blog/v3/draft-posts/{id_b}/publish")
            post_b = payload.get("postId")
            print(f"  publish B (same slug): HTTP {status}, postId={post_b}")
            if post_b:
                posts.append(post_b)
                status, payload = call("GET", f"/blog/v3/posts/{post_b}")
                slug_b_pub = (payload.get("post") or {}).get("slug")
                print(f"  post B actual slug: {slug_b_pub!r}")
                findings["phase_b"]["collision"] = {
                    "second_publish_status": status,
                    "second_post_slug": slug_b_pub,
                    "slug_was_mutated": slug_b_pub != REQUESTED_SLUG,
                }
            else:
                findings["phase_b"]["collision"] = {
                    "second_publish_status": status,
                    "second_post_slug": None,
                    "rejected": True,
                }
        return 0

    finally:
        print("\n== CLEANUP ==")
        for post_id in posts:
            status, _ = call("DELETE", f"/blog/v3/posts/{post_id}")
            print(f"  delete post {post_id}: HTTP {status}")
        for draft_id in drafts:
            status, _ = call("DELETE", f"/blog/v3/draft-posts/{draft_id}")
            print(f"  delete draft {draft_id}: HTTP {status}")
        print("\n== FINDINGS ==")
        print(json.dumps(findings, indent=2))


if __name__ == "__main__":
    sys.exit(main())
