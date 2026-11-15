"""Hacker News connector via the official Algolia search API (no key needed).

Status in this container: host `hn.algolia.com` is blocked by the environment's
network policy, so every call returns access_status=network_blocked and is
logged as an access failure. The code path is real and will work unchanged in
an environment where that host is allowed.
"""
from __future__ import annotations

import html
import re
from typing import Any

from .base import (ERROR, NETWORK_BLOCKED, OK, RATE_LIMITED, Capability,
                   Connector, FetchResult, RawItem, http_get)

API = "https://hn.algolia.com/api/v1/search"
_TAG = re.compile(r"<[^>]+>")


def clean_hn(text: str) -> str:
    """HN returns comment_text as HTML (<p>, <i>, &quot;). Decode it, or the
    markup leaks into stored quotes and corrupts matching."""
    if not text:
        return ""
    text = text.replace("<p>", "\n\n").replace("</p>", "")
    text = _TAG.sub(" ", text)
    text = html.unescape(text)
    return re.sub(r"[ \t]+", " ", text).strip()


class HackerNewsConnector(Connector):
    platform = "hackernews"
    probe_url = "https://hn.algolia.com/api/v1/search?query=test&hitsPerPage=1"
    capability = Capability(
        platform="hackernews",
        access_mechanism="Official HN Search API (Algolia), keyless",
        data_available="Story/comment text, author, created_at, points, url, objectID",
        credentials_required=[],
        limits="~10k req/hour, soft. Comments returned as separate tagged objects.",
        tos_notes="Public API over public content. Attribution by permalink.",
        needs_human="None once the host is reachable.",
    )

    def available(self) -> tuple[bool, str]:
        return True, ""

    def search(self, query: str, limit: int = 20, comments: bool = True, **kw: Any) -> FetchResult:
        params = {
            "query": query,
            "hitsPerPage": min(max(limit, 1), 100),
            "tags": "comment" if comments else "story",
        }
        code, err, body = http_get(API, params=params)
        if err:
            return FetchResult(access_status=NETWORK_BLOCKED, reason=err, endpoint=API)
        if code == 429:
            return FetchResult(access_status=RATE_LIMITED, http_code=code, endpoint=API)
        if code != 200 or not isinstance(body, dict):
            return FetchResult(access_status=ERROR, http_code=code,
                               reason=str(body)[:200], endpoint=API)
        items = []
        for h in body.get("hits", []):
            text = clean_hn(h.get("comment_text") or h.get("story_text") or h.get("title") or "")
            if not text.strip():
                continue
            oid = h.get("objectID")
            items.append(RawItem(
                external_id=f"hn:{oid}",
                text=text,
                kind="comment" if h.get("comment_text") else "post",
                url=f"https://news.ycombinator.com/item?id={oid}",
                title=h.get("story_title") or h.get("title"),
                author_ref=h.get("author"),
                published_at=h.get("created_at"),
                extraction_method="read_full",
                raw_meta={"points": h.get("points"), "story_id": h.get("story_id")},
            ))
        return FetchResult(items=items, access_status=OK, http_code=code, endpoint=API,
                           reason=f"nbHits={body.get('nbHits')}")
