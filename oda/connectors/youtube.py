"""YouTube connector via the official Data API v3.

Host `www.googleapis.com` IS reachable from this container, so this connector
becomes usable the moment the user supplies YOUTUBE_API_KEY. Captions/transcripts
are NOT fetched: the captions.download endpoint requires the video owner's
OAuth, so transcript work is routed to a human task instead of scraping.
"""
from __future__ import annotations

import os
from typing import Any

from .base import (ERROR, NETWORK_BLOCKED, NOT_AUTHORIZED, OK, RATE_LIMITED,
                   Capability, Connector, FetchResult, RawItem, http_get)

SEARCH = "https://www.googleapis.com/youtube/v3/search"
THREADS = "https://www.googleapis.com/youtube/v3/commentThreads"
VIDEOS = "https://www.googleapis.com/youtube/v3/videos"


def _fetch_stats(video_ids: list[str], key: str) -> dict[str, dict]:
    """videos.list costs 1 quota unit for up to 50 ids and is the only way to
    get view/like counts: search.list does not return them."""
    stats: dict[str, dict] = {}
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i:i + 50]
        code, err, body = http_get(VIDEOS, params={
            "part": "statistics", "id": ",".join(chunk), "key": key})
        if err or code != 200 or not isinstance(body, dict):
            continue
        for it in body.get("items", []):
            st = it.get("statistics") or {}
            stats[it.get("id")] = {
                "views": st.get("viewCount"), "likes": st.get("likeCount"),
                "comments_count": st.get("commentCount"),
            }
    return stats


class YouTubeConnector(Connector):
    platform = "youtube"
    probe_url = "https://www.googleapis.com/youtube/v3/i18nLanguages?part=snippet"
    capability = Capability(
        platform="youtube",
        access_mechanism="Official YouTube Data API v3 (search.list, commentThreads.list)",
        data_available="Video title/description/publishedAt/channel; top-level comments + replies",
        credentials_required=["YOUTUBE_API_KEY"],
        limits="10,000 quota units/day. search.list costs 100 units; commentThreads.list costs 1.",
        tos_notes="Captions require the owner's OAuth - transcripts are NOT auto-downloaded. "
                  "Comments may be disabled per video (reported as partial).",
        needs_human="User supplies an API key; transcript review becomes a human task.",
    )

    def search(self, query: str, limit: int = 15, with_comments: bool = True,
               region: str | None = None, lang: str | None = None, **kw: Any) -> FetchResult:
        key = os.environ.get("YOUTUBE_API_KEY")
        if not key:
            return FetchResult(access_status=NOT_AUTHORIZED,
                               reason="missing credentials: YOUTUBE_API_KEY", endpoint=SEARCH)
        params = {"part": "snippet", "q": query, "type": "video",
                  "maxResults": min(max(limit, 1), 50), "key": key}
        if region:
            params["regionCode"] = region
        if lang:
            params["relevanceLanguage"] = lang
        code, err, body = http_get(SEARCH, params=params)
        if err:
            return FetchResult(access_status=NETWORK_BLOCKED, reason=err, endpoint=SEARCH)
        if code == 403:
            msg = (body or {}).get("error", {}).get("message", "") if isinstance(body, dict) else ""
            status = RATE_LIMITED if "quota" in msg.lower() else NOT_AUTHORIZED
            return FetchResult(access_status=status, http_code=code, reason=msg, endpoint=SEARCH)
        if code != 200 or not isinstance(body, dict):
            return FetchResult(access_status=ERROR, http_code=code,
                               reason=str(body)[:200], endpoint=SEARCH)

        video_ids = [(it.get("id") or {}).get("videoId")
                     for it in body.get("items", [])]
        video_ids = [v for v in video_ids if v]
        stats = _fetch_stats(video_ids, key) if video_ids else {}

        items: list[RawItem] = []
        partial = False
        for it in body.get("items", []):
            vid = (it.get("id") or {}).get("videoId")
            sn = it.get("snippet") or {}
            if not vid:
                continue
            desc = sn.get("description") or ""
            items.append(RawItem(
                external_id=f"yt:{vid}", text="\n\n".join(x for x in [sn.get("title"), desc] if x),
                kind="description", url=f"https://www.youtube.com/watch?v={vid}",
                title=sn.get("title"), author_ref=sn.get("channelTitle"),
                published_at=sn.get("publishedAt"),
                extraction_method="metadata_only",   # description != what the video says
                raw_meta={"video_id": vid, "channel_id": sn.get("channelId")},
                engagement={k: int(v) for k, v in (stats.get(vid) or {}).items()
                            if v is not None},
            ))
            if with_comments:
                ccode, cerr, cbody = http_get(THREADS, params={
                    "part": "snippet", "videoId": vid, "maxResults": 50,
                    "order": "relevance", "textFormat": "plainText", "key": key})
                if cerr or ccode != 200 or not isinstance(cbody, dict):
                    partial = True
                    continue
                for th in cbody.get("items", []):
                    cs = ((th.get("snippet") or {}).get("topLevelComment") or {}).get("snippet") or {}
                    txt = cs.get("textDisplay") or ""
                    if not txt.strip():
                        continue
                    items.append(RawItem(
                        external_id=f"yt:c:{th.get('id')}", text=txt, kind="comment",
                        url=f"https://www.youtube.com/watch?v={vid}&lc={th.get('id')}",
                        title=sn.get("title"), author_ref=cs.get("authorDisplayName"),
                        published_at=cs.get("publishedAt"), extraction_method="read_full",
                        raw_meta={"video_id": vid},
                        engagement={
                            **({"likes": int(cs["likeCount"])}
                               if str(cs.get("likeCount", "")).isdigit() else {}),
                            **({"comments_count": int(th["snippet"]["totalReplyCount"])}
                               if str((th.get("snippet") or {}).get("totalReplyCount", "")).isdigit()
                               else {}),
                        },
                    ))
        return FetchResult(items=items, access_status="partial" if partial else OK,
                           http_code=code, endpoint=SEARCH,
                           reason="some videos had comments disabled" if partial else None)
