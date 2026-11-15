"""Stack Exchange connector via the official API 2.3 (keyless tier).

Status in this container: host `api.stackexchange.com` is blocked by the
environment network policy -> access_status=network_blocked, logged.
"""
from __future__ import annotations

import html
import os
import re
from typing import Any

from .base import (ERROR, NETWORK_BLOCKED, OK, RATE_LIMITED, Capability,
                   Connector, FetchResult, RawItem, http_get)

API = "https://api.stackexchange.com/2.3/search/advanced"
_TAG = re.compile(r"<[^>]+>")


def strip_html(s: str) -> str:
    return html.unescape(_TAG.sub(" ", s or "")).strip()


class StackExchangeConnector(Connector):
    platform = "stackexchange"
    probe_url = "https://api.stackexchange.com/2.3/info?site=stackoverflow"
    capability = Capability(
        platform="stackexchange",
        access_mechanism="Official Stack Exchange API 2.3 /search/advanced",
        data_available="Question title, body, tags, score, creation_date, link, owner display name",
        credentials_required=[],
        limits="300 req/day without a key; 10k/day with a free app key (STACKEXCHANGE_KEY).",
        tos_notes="CC BY-SA content; attribution + link required when quoting.",
        needs_human="Optional free app key to raise the daily quota.",
    )

    def available(self) -> tuple[bool, str]:
        return True, ""

    def search(self, query: str, limit: int = 20, site: str = "softwarerecs", **kw: Any) -> FetchResult:
        params = {
            "q": query, "site": site, "pagesize": min(max(limit, 1), 100),
            "filter": "withbody", "order": "desc", "sort": "relevance",
        }
        key = os.environ.get("STACKEXCHANGE_KEY")
        if key:
            params["key"] = key
        code, err, body = http_get(API, params=params)
        if err:
            return FetchResult(access_status=NETWORK_BLOCKED, reason=err, endpoint=API)
        if code in (429, 502):
            return FetchResult(access_status=RATE_LIMITED, http_code=code, endpoint=API)
        if code != 200 or not isinstance(body, dict):
            return FetchResult(access_status=ERROR, http_code=code,
                               reason=str(body)[:200], endpoint=API)
        items = []
        for q in body.get("items", []):
            text = "\n\n".join(x for x in [q.get("title"), strip_html(q.get("body", ""))] if x)
            if not text.strip():
                continue
            items.append(RawItem(
                external_id=f"se:{site}:{q.get('question_id')}",
                text=text, kind="post",
                url=q.get("link"), title=q.get("title"),
                author_ref=(q.get("owner") or {}).get("display_name"),
                published_at=str(q.get("creation_date")),
                extraction_method="read_full",
                raw_meta={"tags": q.get("tags"), "score": q.get("score"),
                          "answers": q.get("answer_count"), "site": site,
                          "license": "CC BY-SA"},
            ))
        return FetchResult(items=items, access_status=OK, http_code=code, endpoint=API,
                           reason=f"quota_remaining={body.get('quota_remaining')}")
