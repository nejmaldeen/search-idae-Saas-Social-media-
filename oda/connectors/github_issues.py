"""GitHub Issues/Discussions connector - VERIFIED WORKING in this container.

GitHub issue bodies and comments are a dense source of real complaints,
feature requests and "is there an alternative to X" discussions. Access is
through the official REST Search API.
"""
from __future__ import annotations

import os
import time
from typing import Any

from .base import (NOT_AUTHORIZED, OK, RATE_LIMITED, ERROR, NETWORK_BLOCKED,
                   Capability, Connector, FetchResult, RawItem, http_get)

API = "https://api.github.com/search/issues"


class GitHubIssuesConnector(Connector):
    platform = "github"
    probe_url = "https://api.github.com/rate_limit"
    capability = Capability(
        platform="github",
        access_mechanism="Official REST Search API (api.github.com/search/issues)",
        data_available="Issue/PR title, body, author login, created_at, html_url, comment count",
        credentials_required=[],   # works unauthenticated at a lower rate limit
        limits="Unauthenticated: 10 search req/min. With GITHUB_API_TOKEN: 30/min. 1000 results per query.",
        tos_notes="Public API, public data. Store URLs + short quotes; do not mirror whole repos.",
        needs_human="Only if a private repo must be searched (requires the user's own token).",
    )

    def available(self) -> tuple[bool, str]:
        return True, ""

    def search(self, query: str, limit: int = 20, **kw: Any) -> FetchResult:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "opportunity-discovery-agent",
        }
        token = os.environ.get("GITHUB_API_TOKEN")  # opt-in only; GH_TOKEN here is invalid
        if token:
            headers["Authorization"] = f"Bearer {token}"

        # Search API requires the is: qualifier.
        q = query if "is:issue" in query or "is:pull-request" in query else f'is:issue {query}'
        params = {"q": q, "per_page": min(max(limit, 1), 100), "sort": "created", "order": "desc"}

        code, err, body = http_get(API, params=params, headers=headers)
        if err:
            return FetchResult(access_status=NETWORK_BLOCKED, reason=err, endpoint=API)
        if code == 403 or code == 429:
            reason = ""
            if isinstance(body, dict):
                reason = body.get("message", "")
            return FetchResult(access_status=RATE_LIMITED, http_code=code,
                               reason=reason or "rate limited", endpoint=API)
        if code == 401:
            return FetchResult(access_status=NOT_AUTHORIZED, http_code=code,
                               reason="token rejected", endpoint=API)
        if code != 200 or not isinstance(body, dict):
            msg = body.get("message") if isinstance(body, dict) else str(body)[:200]
            return FetchResult(access_status=ERROR, http_code=code, reason=msg, endpoint=API)

        items: list[RawItem] = []
        for it in body.get("items", []):
            text_parts = [it.get("title") or "", it.get("body") or ""]
            text = "\n\n".join(p for p in text_parts if p).strip()
            if not text:
                continue
            repo_url = it.get("repository_url") or ""
            items.append(RawItem(
                external_id=f"gh:{it.get('id')}",
                text=text,
                kind="issue",
                url=it.get("html_url"),
                title=it.get("title"),
                author_ref=(it.get("user") or {}).get("login"),
                published_at=it.get("created_at"),
                extraction_method="read_full",
                raw_meta={
                    "repo": repo_url.rsplit("/", 2)[-2:] and "/".join(repo_url.rsplit("/", 2)[-2:]),
                    "comments": it.get("comments"),
                    "state": it.get("state"),
                    "labels": [l.get("name") for l in (it.get("labels") or [])],
                    "reactions": (it.get("reactions") or {}).get("total_count"),
                },
            ))
        return FetchResult(items=items, access_status=OK, http_code=code,
                           endpoint=API, reason=f"total_count={body.get('total_count')}")
