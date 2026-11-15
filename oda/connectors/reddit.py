"""Reddit connector via the official OAuth API (script-app client credentials).

ACCESS STATUS: Reddit's Responsible Builder Policy requires *explicit prior
approval* to access Reddit data through the API - registering a script app is
necessary but NOT sufficient. This connector therefore sits in the same class
as TikTok: the code is complete, but lawful use depends on an approval the
user must obtain. Nothing here attempts to work around that.

Requires REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET from
https://www.reddit.com/prefs/apps plus approved API access.
"""
from __future__ import annotations

import os
from typing import Any, Optional

from .base import (ERROR, NETWORK_BLOCKED, NOT_AUTHORIZED, OK, RATE_LIMITED,
                   Capability, Connector, FetchResult, RawItem)

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
SEARCH_URL = "https://oauth.reddit.com/search"
UA = "opportunity-discovery-agent/0.1 (research; contact via app owner)"


class RedditConnector(Connector):
    platform = "reddit"
    probe_url = "https://www.reddit.com/robots.txt"
    capability = Capability(
        platform="reddit",
        access_mechanism="Official OAuth2 API (registered script app) + approved API access",
        data_available="Post title/selftext, subreddit, author, created_utc, permalink, score; comments via /comments",
        credentials_required=["REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET"],
        limits="100 queries/min per OAuth client once approved. Approval is gated by Reddit.",
        tos_notes="Responsible Builder Policy: PRIOR APPROVAL REQUIRED before accessing Reddit "
                  "data via the API. No bulk redistribution; store IDs + links + short quotes. "
                  "Registering multiple accounts for one use case is prohibited.",
        needs_human="User must (1) register a script app AND (2) request and receive explicit "
                    "API access approval from Reddit before any collection is lawful.",
    )

    def _token(self) -> tuple[Optional[str], Optional[str]]:
        import requests
        from .base import CA_BUNDLE
        cid = os.environ.get("REDDIT_CLIENT_ID")
        sec = os.environ.get("REDDIT_CLIENT_SECRET")
        if not cid or not sec:
            return None, "missing REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET"
        verify: Any = CA_BUNDLE if os.path.exists(CA_BUNDLE) else True
        try:
            r = requests.post(TOKEN_URL, auth=(cid, sec),
                              data={"grant_type": "client_credentials"},
                              headers={"User-Agent": UA}, timeout=30, verify=verify)
        except requests.exceptions.RequestException as e:
            return None, f"network error: {e.__class__.__name__}: {e}"
        if r.status_code != 200:
            return None, f"token endpoint HTTP {r.status_code}"
        return r.json().get("access_token"), None

    def search(self, query: str, limit: int = 20, subreddit: Optional[str] = None,
               **kw: Any) -> FetchResult:
        ok, why = self.available()
        if not ok:
            return FetchResult(access_status=NOT_AUTHORIZED, reason=why, endpoint=SEARCH_URL)
        token, err = self._token()
        if err:
            status = NETWORK_BLOCKED if "network error" in err else NOT_AUTHORIZED
            return FetchResult(access_status=status, reason=err, endpoint=TOKEN_URL)

        from .base import http_get
        url = f"https://oauth.reddit.com/r/{subreddit}/search" if subreddit else SEARCH_URL
        params = {"q": query, "limit": min(max(limit, 1), 100), "sort": "relevance",
                  "type": "link", "raw_json": 1}
        if subreddit:
            params["restrict_sr"] = "true"
        code, nerr, body = http_get(url, params=params,
                                    headers={"Authorization": f"Bearer {token}", "User-Agent": UA})
        if nerr:
            return FetchResult(access_status=NETWORK_BLOCKED, reason=nerr, endpoint=url)
        if code == 429:
            return FetchResult(access_status=RATE_LIMITED, http_code=code, endpoint=url)
        if code in (401, 403):
            return FetchResult(access_status=NOT_AUTHORIZED, http_code=code, endpoint=url)
        if code != 200 or not isinstance(body, dict):
            return FetchResult(access_status=ERROR, http_code=code,
                               reason=str(body)[:200], endpoint=url)
        items = []
        for ch in (body.get("data") or {}).get("children", []):
            d = ch.get("data") or {}
            text = "\n\n".join(x for x in [d.get("title"), d.get("selftext")] if x)
            if not text.strip():
                continue
            items.append(RawItem(
                external_id=f"reddit:{d.get('id')}",
                text=text, kind="post",
                url="https://www.reddit.com" + (d.get("permalink") or ""),
                title=d.get("title"), author_ref=d.get("author"),
                published_at=str(d.get("created_utc")),
                extraction_method="read_full",
                raw_meta={"subreddit": d.get("subreddit"), "score": d.get("score"),
                          "num_comments": d.get("num_comments")},
            ))
        return FetchResult(items=items, access_status=OK, http_code=code, endpoint=url)
