"""Commercial data-provider connector (Apify-compatible).

Why this exists
---------------
For a commercial user outside the academic programmes, several platforms have
NO official self-serve path at all (verified Nov 2026):
  * TikTok   - Research API excludes commercial users entirely.
  * Reddit   - new public Data API requests closed 31 Oct 2026.
  * G2/Capterra - no public read API.
X has an official pay-per-use API, and Instagram's Graph API cannot search
public posts it does not own. So a commercial data provider is the only route
that covers these sources from one integration.

How it works
------------
This connector calls the PROVIDER's own documented REST API with the user's
token. It performs no collection itself: the provider runs the job and returns
structured rows. Swapping providers or actors is configuration, not code.

Compliance posture
------------------
Project decision D-10: the operator accepts a commercial intermediary and is
responsible for the provider's and target platforms' terms. Each run records
the provider, actor and cost so usage stays auditable.

Configuration (environment)
---------------------------
  APIFY_TOKEN                    provider API token (required)
  ODA_PROVIDER_BASE              override base URL (default Apify)
  ODA_ACTOR_<PLATFORM>           override the actor id, e.g.
                                 ODA_ACTOR_TIKTOK=clockworks~tiktok-scraper
  ODA_ACTOR_TIMEOUT              seconds to wait for a synchronous run (default 180)
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable, Optional

from ..textutil import short_hash
from .base import (ERROR, NETWORK_BLOCKED, NOT_AUTHORIZED, OK, PARTIAL,
                   RATE_LIMITED, CA_BUNDLE, Capability, Connector, FetchResult,
                   RawItem, extract_engagement, within_days)

DEFAULT_BASE = "https://api.apify.com/v2"

# A post caption is mostly hashtags; the pain lives in the comments. For
# platforms with a dedicated comments actor we run two stages:
#   1) search actor  -> post/video URLs (captions kept as context)
#   2) comments actor -> the actual user voices on those posts
# Overridable with ODA_COMMENT_ACTOR_<PLATFORM>; set to "" to disable stage 2.
DEFAULT_COMMENT_ACTORS: dict[str, str] = {
    "tiktok": "clockworks~tiktok-comments-scraper",
    "instagram": "apify~instagram-comment-scraper",
}

# Built from each comments actor's published input schema.
COMMENT_INPUTS: dict[str, Callable[..., dict]] = {
    "tiktok": lambda urls, n, replies=0: {
        "postURLs": urls, "commentsPerPost": max(1, n),
        "maxRepliesPerComment": max(0, int(replies))},
    "instagram": lambda urls, n, replies=0: {
        "directUrls": urls, "resultsLimit": max(1, n),
        "includeNestedComments": bool(replies)},
}

# Actor ids change and get deprecated; every one is overridable by env var.
DEFAULT_ACTORS: dict[str, str] = {
    "tiktok": "clockworks~tiktok-scraper",
    "instagram": "apify~instagram-scraper",
    "x": "apidojo~tweet-scraper",
    "reddit": "fatihtahta~reddit-scraper-search-fast",
    "snapchat": "parseforge~snapchat-scraper",
    "g2": "apify~web-scraper",
    "capterra": "apify~web-scraper",
}

# Each actor takes a different input shape. Builders are small and explicit so
# a changed actor is a one-line fix.
# Built from each actor's published input schema (GET /v2/acts/<id>/builds/default),
# not from guesswork. Re-check the schema if an actor starts rejecting input.
def _since_date(kw: dict) -> Optional[str]:
    """Translate `since_days` into an ISO date. Recency matters: a complaint
    about a product from three years ago may describe a problem that no longer
    exists."""
    days = kw.get("since_days")
    if not days:
        return None
    import datetime as _dt
    return (_dt.date.today() - _dt.timedelta(days=int(days))).isoformat()


def _in_tiktok(q: str, n: int, **kw: Any) -> dict:
    # `maxProfilesPerQuery` must be >= 1 when present, so it is omitted entirely:
    # we want search results, not profile crawls.
    out: dict = {"searchQueries": [q], "resultsPerPage": max(1, n),
                 "searchSection": "", "excludePinnedPosts": False}
    since = _since_date(kw)
    if since:
        out["oldestPostDateUnified"] = since
    return out


def _in_instagram(q: str, n: int, **kw: Any) -> dict:
    """Instagram: `search` returns HASHTAG METADATA, not posts (verified live).
    Posts only come back through `directUrls`, so a bare query is turned into
    the hashtag explore URL. Each post also carries `latestComments`, which is
    where the user voices are - no second actor call needed."""
    from urllib.parse import quote
    urls = kw.get("direct_urls")
    if not urls:
        if q.startswith("http"):
            urls = [q]
        else:
            tag = quote(q.lstrip("#").replace(" ", ""), safe="")
            urls = [f"https://www.instagram.com/explore/tags/{tag}"]
    out: dict = {"directUrls": urls, "resultsType": "posts",
                 "resultsLimit": max(1, n), "addParentData": False}
    since = _since_date(kw)
    if since:
        out["onlyPostsNewerThan"] = since
    return out


def _in_x(q: str, n: int, **kw: Any) -> dict:
    out: dict = {"searchTerms": [q], "maxItems": max(1, n), "sort": "Latest"}
    if kw.get("lang"):
        out["tweetLanguage"] = kw["lang"]
    since = _since_date(kw)
    if since:
        out["start"] = since
    return out


def _in_reddit(q: str, n: int, **kw: Any) -> dict:
    """Reddit needs RESIDENTIAL proxies. On a free plan the run succeeds but
    saves 0 records, logging 'temporary Reddit access issue' - Reddit blocks
    datacenter IPs. Verified live 2026-11-15."""
    out: dict = {"queries": [q], "maxItems": max(1, n),
                 "sort": kw.get("sort", "relevance"), "timeframe": "all"}
    if kw.get("with_comments", True):
        out["scrapeComments"] = True
        out["maxComments"] = int(kw.get("comments_per_post", 20))
    if kw.get("subreddit"):
        out["subredditName"] = kw["subreddit"]
    return out


def _in_snapchat(q: str, n: int, **kw: Any) -> dict:
    """Snapchat has NO keyword search on any available actor (verified against
    every Snapchat actor on the store, 2026-11-15). Collection is therefore
    PROFILE-DRIVEN: the operator supplies the accounts to monitor, and `q` is
    read as a username unless explicit `usernames` are passed.

    In exchange it returns the richest payload of any platform here: view /
    share / comment counts, the comment bodies, and a video transcript.
    """
    names = kw.get("usernames") or [q.lstrip("@").strip()]
    return {"usernames": [n_ for n_ in names if n_],
            "maxItems": max(1, n),
            "resultType": kw.get("result_type", "spotlight"),
            "includeTranscripts": bool(kw.get("include_transcripts", True)),
            "maxCommentsPerSpotlight": int(kw.get("comments_per_post", 25))}


def _in_web(q: str, n: int, **kw: Any) -> dict:
    urls = kw.get("start_urls") or []
    return {"startUrls": [{"url": u} for u in urls],
            "maxRequestsPerCrawl": max(1, n),
            "proxyConfiguration": {"useApifyProxy": True}}


INPUT_BUILDERS: dict[str, Callable[..., dict]] = {
    "tiktok": _in_tiktok, "instagram": _in_instagram, "x": _in_x,
    "reddit": _in_reddit, "snapchat": _in_snapchat,
    "g2": _in_web, "capterra": _in_web,
}

# Platforms that cannot be searched by keyword and must be given accounts.
PROFILE_ONLY = ("snapchat",)

# Actor outputs use different field names. These are tried in order.
_TEXT_KEYS = ("text", "comment", "caption", "content", "body", "selftext",
              "title", "fullText", "message", "description", "reviewText")
# Comment rows carry the PARENT post's url under various names - that is the
# correct provenance for a comment, so the evidence chain is never broken.
_URL_KEYS = ("url", "postUrl", "webVideoUrl", "videoWebUrl", "submittedVideoUrl",
             "link", "permalink", "tweetUrl", "commentUrl", "videoUrl", "input")
_ID_KEYS = ("id", "cid", "postId", "tweetId", "commentId", "videoId", "itemId")
# Nested containers are checked too (authorMeta.name, author.name, user.username).
_AUTHOR_KEYS = ("ownerUsername", "username", "authorName", "authorMeta", "author",
                "owner", "user", "userName", "uniqueId", "screen_name",
                "handle", "nickName", "name")
_DATE_KEYS = ("timestamp", "createdAt", "created_at", "createTimeISO",
              "uploadedAt", "publishedAt", "postedAt", "date", "created_utc",
              "time", "scrapedAt")
_TITLE_KEYS = ("title", "postTitle", "videoTitle", "headline")


def _first(d: dict, keys: tuple[str, ...]) -> Optional[str]:
    for k in keys:
        v = d.get(k)
        if isinstance(v, dict):
            for nk in ("name", "username", "uniqueId", "userName",
                       "screen_name", "nickName", "text", "url"):
                if v.get(nk):
                    return str(v[nk])
            continue
        if v not in (None, "", [], {}):
            return str(v)
    return None


# Some actors signal "nothing found" with sentinel rows rather than an empty
# list or an error. Treating those as ordinary unmappable rows would report a
# silent success, which is exactly what criterion C09 forbids.
_SENTINEL_KEYS = ("noResults", "no_results", "error", "errorMessage", "warning")


def is_sentinel_row(row: Any) -> Optional[str]:
    """Return a reason string when a row is a 'nothing found' / error marker."""
    if not isinstance(row, dict):
        return None
    # A real content row has text; a sentinel is a bare flag.
    if any(k in row for k in _TEXT_KEYS):
        return None
    for k in _SENTINEL_KEYS:
        if k in row and row[k]:
            v = row[k]
            return f"{k}={v if not isinstance(v, (dict, list)) else str(v)[:80]}"
    return None


def _transcript_meta(row: dict) -> dict:
    """What the video actually SAYS, where the provider exposes it.

    Three shapes exist in the wild:
      * an inline transcript string          (Snapchat)
      * an AI-written description/summary    (TikTok, paid add-on)
      * subtitle tracks behind a CDN link    (TikTok, incl. ara-SA)
    The caption alone is usually hashtags, so this is what makes a video's
    content readable at all.
    """
    out: dict = {}
    text = (row.get("transcript") or row.get("transcription")
            or row.get("captions") or row.get("subtitles"))
    if isinstance(text, str) and text.strip():
        out["transcript"] = text.strip()

    vm = row.get("videoMeta") if isinstance(row.get("videoMeta"), dict) else {}
    for key in ("aiVideoSummary", "aiVideoDescription"):
        v = vm.get(key) or row.get(key)
        if isinstance(v, str) and v.strip():
            out.setdefault("transcript", v.strip())
            out["transcript_source"] = key
            break

    links = vm.get("subtitleLinks") or row.get("subtitleLinks") or []
    if isinstance(links, list) and links:
        langs, urls = [], {}
        for s in links:
            if isinstance(s, dict) and s.get("language"):
                langs.append(s["language"])
                if s.get("downloadLink"):
                    urls[s["language"]] = s["downloadLink"]
        if langs:
            out["subtitle_languages"] = langs
            out["subtitle_links"] = urls
    if vm.get("transcriptionLink") or row.get("transcriptionLink"):
        out["transcription_link"] = vm.get("transcriptionLink") or row.get("transcriptionLink")
    return out


def map_item(row: dict, platform: str) -> Optional[RawItem]:
    """Map one provider row to a RawItem. Returns None when there is no text."""
    if not isinstance(row, dict):
        return None
    text = _first(row, _TEXT_KEYS)
    if not text or not text.strip():
        return None
    url = _first(row, _URL_KEYS)
    ext = _first(row, _ID_KEYS) or short_hash(text + (url or ""), 20)
    kind = "comment" if any(k in row for k in ("comment", "commentUrl", "replyCount")) else "post"
    return RawItem(
        external_id=f"{platform}:{ext}",
        text=text.strip(),
        kind=kind,
        url=url,
        title=_first(row, _TITLE_KEYS),
        author_ref=_first(row, _AUTHOR_KEYS),
        published_at=_first(row, _DATE_KEYS),
        extraction_method="read_full",
        raw_meta={"provider": "apify", "platform": platform,
                  "hashtags": row.get("hashtags"),
                  "language": row.get("language") or row.get("textLanguage"),
                  **_transcript_meta(row)},
        engagement=extract_engagement(row),
    )


class ProviderConnector(Connector):
    """One commercial-provider-backed connector per target platform."""

    def __init__(self, platform: str, capability: Capability):
        self.platform = platform
        self.capability = capability

    # ---- configuration helpers -------------------------------------------
    @property
    def token(self) -> Optional[str]:
        return os.environ.get("APIFY_TOKEN")

    @property
    def base(self) -> str:
        return os.environ.get("ODA_PROVIDER_BASE", DEFAULT_BASE).rstrip("/")

    @property
    def actor(self) -> str:
        return os.environ.get(f"ODA_ACTOR_{self.platform.upper()}",
                              DEFAULT_ACTORS.get(self.platform, ""))

    @property
    def comment_actor(self) -> str:
        return os.environ.get(f"ODA_COMMENT_ACTOR_{self.platform.upper()}",
                              DEFAULT_COMMENT_ACTORS.get(self.platform, ""))

    def available(self) -> tuple[bool, str]:
        if not self.token:
            return False, "missing credentials: APIFY_TOKEN"
        if not self.actor:
            return False, f"no actor configured; set ODA_ACTOR_{self.platform.upper()}"
        return True, ""

    def probe(self, timeout: int = 15) -> tuple[bool, str]:
        """Check the provider answers and the token is valid."""
        if not self.token:
            return False, "missing credentials: APIFY_TOKEN"
        import requests
        verify: Any = CA_BUNDLE if os.path.exists(CA_BUNDLE) else True
        try:
            r = requests.get(f"{self.base}/users/me",
                             headers={"Authorization": f"Bearer {self.token}"},
                             timeout=timeout, verify=verify)
        except requests.exceptions.RequestException as e:
            return False, f"network error: {e.__class__.__name__}: {e}"
        if r.status_code in (401, 403):
            return False, f"provider rejected the token (HTTP {r.status_code})"
        if r.status_code >= 500:
            return False, f"provider error HTTP {r.status_code}"
        return True, ""

    # ---- collection -------------------------------------------------------
    def _run_actor(self, actor: str, payload: dict) -> tuple[Optional[list], FetchResult]:
        """Run one actor synchronously. Returns (rows, error_result_or_None)."""
        timeout = int(os.environ.get("ODA_ACTOR_TIMEOUT", "180"))
        endpoint = f"{self.base}/acts/{actor}/run-sync-get-dataset-items"
        import requests
        verify: Any = CA_BUNDLE if os.path.exists(CA_BUNDLE) else True
        try:
            r = requests.post(
                endpoint, params={"timeout": timeout, "memory": 1024},
                headers={"Authorization": f"Bearer {self.token}",
                         "Content-Type": "application/json"},
                data=json.dumps(payload), timeout=timeout + 30, verify=verify)
        except requests.exceptions.ProxyError as e:
            return None, FetchResult(access_status=NETWORK_BLOCKED, endpoint=endpoint,
                                     reason=f"host not allowed by this environment: {e.__class__.__name__}")
        except requests.exceptions.RequestException as e:
            return None, FetchResult(access_status=NETWORK_BLOCKED, endpoint=endpoint,
                                     reason=f"network error: {e.__class__.__name__}: {e}")
        if r.status_code in (401, 403):
            return None, FetchResult(access_status=NOT_AUTHORIZED, http_code=r.status_code,
                                     endpoint=endpoint, reason="provider rejected the token")
        if r.status_code == 429:
            return None, FetchResult(access_status=RATE_LIMITED, http_code=r.status_code,
                                     endpoint=endpoint, reason="provider rate limit / quota")
        if r.status_code == 404:
            return None, FetchResult(access_status=ERROR, http_code=404, endpoint=endpoint,
                                     reason=f"actor '{actor}' not found - it may be deprecated; "
                                            f"override with ODA_ACTOR_{self.platform.upper()}")
        if r.status_code >= 400:
            return None, FetchResult(access_status=ERROR, http_code=r.status_code,
                                     endpoint=endpoint, reason=r.text[:300])
        try:
            rows = r.json()
        except ValueError:
            return None, FetchResult(access_status=ERROR, http_code=r.status_code,
                                     endpoint=endpoint, reason="provider returned non-JSON")
        if isinstance(rows, dict):
            rows = rows.get("items") or rows.get("data") or []
        if not isinstance(rows, list):
            return None, FetchResult(access_status=ERROR, http_code=r.status_code,
                                     endpoint=endpoint, reason="unexpected payload shape")
        return rows, FetchResult(access_status=OK, http_code=r.status_code, endpoint=endpoint)

    def search(self, query: str, limit: int = 25, **kw: Any) -> FetchResult:
        ok, why = self.available()
        if not ok:
            return FetchResult(access_status=NOT_AUTHORIZED, reason=why,
                               endpoint=self.capability.access_mechanism)

        builder = INPUT_BUILDERS.get(self.platform)
        if builder is None:
            return FetchResult(access_status=ERROR,
                               reason=f"no input builder for {self.platform}")
        payload = {k: v for k, v in builder(query, limit, **kw).items() if v is not None}

        rows, err = self._run_actor(self.actor, payload)
        if rows is None:
            return err
        # If the actor answered ONLY with sentinel rows, that is a real
        # negative result, not a successful empty page - say so plainly.
        if rows and all(is_sentinel_row(r) for r in rows):
            reasons = sorted({is_sentinel_row(r) or "" for r in rows})
            return FetchResult(
                access_status=ERROR, http_code=200,
                endpoint=f"{self.base}/acts/{self.actor}",
                reason=f"actor={self.actor} returned {len(rows)} marker row(s) and no "
                       f"content: {'; '.join(reasons)[:160]}. The actor reached no "
                       f"results for this query (upstream block, quota, or genuinely "
                       f"nothing matching).")

        items, skipped = [], 0
        # (url, comment_count) so stage 2 can skip posts that have no comments:
        # sending those to the comments actor costs money and returns nothing.
        candidates: list[tuple[str, int]] = []
        sentinels: list[str] = []
        for row in rows:
            sentinel = is_sentinel_row(row)
            if sentinel:
                sentinels.append(sentinel)
                continue
            it = map_item(row, self.platform)
            if it is None:
                skipped += 1
                continue
            items.append(it)
            if it.url:
                candidates.append((it.url, (it.engagement or {}).get("comments_count", -1)))

        # -1 means the platform did not report a count: keep those, they may
        # still have comments. 0 means it reported none, so skip them.
        commented = [u for u, n in candidates if n != 0]
        post_urls = commented or [u for u, _ in candidates]

        # Some actors embed comments inside each post row. Expanding them here
        # is free: no extra actor run and no extra cost.
        nested = 0

        def _expand(container: dict, parent_url: Optional[str]) -> None:
            nonlocal nested
            for key in ("latestComments", "comments", "replies"):
                for c in (container.get(key) or []):
                    if not isinstance(c, dict):
                        continue
                    ci = map_item(c, self.platform)
                    if ci is None:
                        continue
                    ci.kind = "comment"
                    if not ci.url:
                        ci.url = parent_url
                    items.append(ci)
                    nested += 1
                    _expand(c, ci.url or parent_url)   # replies-to-replies

        for row in rows:
            if isinstance(row, dict):
                _expand(row, _first(row, _URL_KEYS))

        notes = [f"search_actor={self.actor} rows={len(rows)} mapped={len(items) - nested}"]
        if nested:
            notes.append(f"embedded_comments={nested}")
        partial = bool(skipped)

        # ---- stage 2: the comments on those posts, where the pain actually is
        cactor = self.comment_actor
        want_comments = kw.get("with_comments", True)
        if cactor and want_comments and post_urls and self.platform in COMMENT_INPUTS:
            max_posts = int(kw.get("max_comment_posts", 10))
            per_post = int(kw.get("comments_per_post", 30))
            replies = int(kw.get("replies_per_comment", 0))
            cpayload = COMMENT_INPUTS[self.platform](post_urls[:max_posts], per_post,
                                                     replies=replies)
            crows, cerr = self._run_actor(cactor, cpayload)
            if crows is None:
                partial = True
                notes.append(f"comments_actor={cactor} FAILED: {cerr.reason}")
            else:
                cmapped = 0
                for row in crows:
                    it = map_item(row, self.platform)
                    if it is None:
                        skipped += 1
                        continue
                    it.kind = "comment"
                    if not it.url and post_urls:
                        it.url = post_urls[0]
                    items.append(it)
                    cmapped += 1
                    if isinstance(row, dict):
                        _expand(row, it.url)   # nested replies on this comment
                notes.append(f"comments_actor={cactor} rows={len(crows)} mapped={cmapped}")

        if sentinels:
            partial = True
            notes.append(f"marker_rows={len(sentinels)} ({sentinels[0][:60]})")

        # Client-side recency guard. Server-side filters are applied above where
        # the actor supports one; this enforces the window everywhere, including
        # platforms that expose no date filter at all (Snapchat).
        since_days = kw.get("since_days")
        if since_days:
            kept, dropped, undated = [], 0, 0
            for it in items:
                verdict = within_days(it.published_at, int(since_days))
                if verdict is False:
                    dropped += 1
                    continue
                if verdict is None:
                    undated += 1          # keep, but say so
                kept.append(it)
            items = kept
            notes.append(f"recency<={since_days}d: dropped={dropped} undated_kept={undated}")

        # Optional transcript stage for platforms whose payload carries none
        # (Instagram reels). Snapchat and TikTok supply theirs inline.
        if kw.get("with_transcripts"):
            from ..transcripts import DEFAULT_TRANSCRIPT_ACTORS, transcript_for_item
            if self.platform in DEFAULT_TRANSCRIPT_ACTORS:
                budget = int(kw.get("max_transcripts", 3))
                got = 0
                for it in [x for x in items if x.kind != "comment"][:budget]:
                    t = transcript_for_item(self.platform, it.url,
                                            raw_meta=it.raw_meta,
                                            check_availability=False)
                    if not t.ok:
                        continue
                    got += 1
                    items.append(RawItem(
                        external_id=f"{self.platform}:t:{it.external_id}",
                        text=t.text, kind="transcript", url=it.url,
                        author_ref=it.author_ref, published_at=it.published_at,
                        extraction_method="read_full",
                        raw_meta={"transcript_source": t.source,
                                  "transcript_segments": t.segments}))
                notes.append(f"transcripts={got}")

        notes.append(f"skipped={skipped}")
        return FetchResult(items=items,
                           access_status=PARTIAL if (partial and items) else OK,
                           http_code=200, endpoint=f"{self.base}/acts/{self.actor}",
                           reason=" | ".join(notes))


# --------------------------------------------------------------------------
_CAPS = {
    "tiktok": Capability(
        platform="tiktok",
        access_mechanism="Commercial provider (Apify-compatible) REST API",
        data_available="Video metadata, captions and comments returned by the actor",
        credentials_required=["APIFY_TOKEN"],
        limits="Billed per result by the provider (~$1.70-3.70 / 1,000 as of Nov 2026).",
        tos_notes="TikTok's Research API excludes commercial users, so no official "
                  "self-serve path exists. Operator accepts provider + platform terms (D-10).",
        needs_human="Supply APIFY_TOKEN and allow api.apify.com in the network policy."),
    "instagram": Capability(
        platform="instagram",
        access_mechanism="Commercial provider (Apify-compatible) REST API",
        data_available="Post captions and comments by hashtag/profile/URL",
        credentials_required=["APIFY_TOKEN"],
        limits="~$1.50-2.70 / 1,000 results as of Nov 2026.",
        tos_notes="Graph API cannot search public posts the app does not own. "
                  "Operator accepts provider + platform terms (D-10).",
        needs_human="Supply APIFY_TOKEN and allow api.apify.com."),
    "x": Capability(
        platform="x",
        access_mechanism="Commercial provider REST API (official X API also exists, pay-per-use)",
        data_available="Tweets matching a search term, author, timestamp, engagement",
        credentials_required=["APIFY_TOKEN"],
        limits="Provider per-result billing. Official X alternative: pay-per-use, "
               "~$0.005 per post read, no free tier (Nov 2026).",
        tos_notes="An official paid route exists; the provider route is the cheaper one. "
                  "Operator accepts the terms (D-10).",
        needs_human="Supply APIFY_TOKEN, or an X_BEARER_TOKEN for the official API."),
    "reddit": Capability(
        platform="reddit",
        access_mechanism="Commercial provider REST API",
        data_available="Posts and comments by search term or subreddit",
        credentials_required=["APIFY_TOKEN"],
        limits="~$0.75-3.40 / 1,000 results. REQUIRES A PAID PLAN: Reddit blocks "
               "datacenter proxies, so a free-plan run saves 0 records. Override the "
               "actor with ODA_ACTOR_REDDIT.",
        tos_notes="Reddit closed new public Data API requests on 31 Oct 2026, so no "
                  "official self-serve path remains. Operator accepts the terms (D-10).",
        needs_human="Supply APIFY_TOKEN and allow api.apify.com."),
    "snapchat": Capability(
        platform="snapchat",
        access_mechanism="Commercial provider REST API (profile-driven; no keyword search)",
        data_available="Spotlight clips: title, description, hashtags, VIDEO TRANSCRIPT, "
                       "comment bodies, viewCount/shareCount/commentCount/boostCount, "
                       "creator subscriber count, upload date",
        credentials_required=["APIFY_TOKEN"],
        limits="NO KEYWORD SEARCH on any available actor: collection is driven by a list "
               "of usernames the operator supplies, so Snapchat is a MONITORING source, "
               "not a DISCOVERY source. Billed per result by the provider.",
        tos_notes="Snap has no official public-content API; its developer surface is ads, "
                  "Snap Kit and an OAuth-gated Public Profile API. Operator accepts the "
                  "provider and platform terms (D-10).",
        needs_human="Operator supplies the Saudi accounts to monitor (there is no way to "
                    "discover them through this API)."),
    "g2": Capability(
        platform="g2",
        access_mechanism="Commercial provider generic web actor (needs start URLs)",
        data_available="Review text from the URLs supplied by the operator",
        credentials_required=["APIFY_TOKEN"],
        limits="Billed per page crawled. Requires explicit start_urls.",
        tos_notes="No public read API exists. Operator accepts the terms (D-10).",
        needs_human="Supply APIFY_TOKEN and the product review URLs to collect."),
    "capterra": Capability(
        platform="capterra",
        access_mechanism="Commercial provider generic web actor (needs start URLs)",
        data_available="Review text from the URLs supplied by the operator",
        credentials_required=["APIFY_TOKEN"],
        limits="Billed per page crawled. Requires explicit start_urls.",
        tos_notes="No public read API exists. Operator accepts the terms (D-10).",
        needs_human="Supply APIFY_TOKEN and the product review URLs to collect."),
}


def build_provider_connectors() -> dict[str, ProviderConnector]:
    return {name: ProviderConnector(name, cap) for name, cap in _CAPS.items()}
