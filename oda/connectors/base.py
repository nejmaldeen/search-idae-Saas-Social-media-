"""Connector contract.

Two things are deliberately separated:
  * `supported`  - the code for this integration exists and is exercised.
  * `available`  - this container actually has credentials + network to use it.

A connector that cannot run returns a FetchResult with a non-ok access_status
and a reason. It never fabricates items.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Optional

OK = "ok"
DENIED = "denied"
NOT_AUTHORIZED = "not_authorized"
NETWORK_BLOCKED = "network_blocked"
RATE_LIMITED = "rate_limited"
ERROR = "error"
PARTIAL = "partial"

CA_BUNDLE = "/root/.ccr/ca-bundle.crt"


ENGAGEMENT_FIELDS = ("views", "likes", "comments_count", "shares", "saves",
                     "author_followers")

# Every platform names these differently. Listed most-specific first so a
# generic key never shadows the right one.
_ENGAGEMENT_ALIASES: dict[str, tuple[str, ...]] = {
    "views": ("viewCount", "playCount", "views", "view_count", "viewsCount",
              "play_count", "impressions"),
    "likes": ("diggCount", "likesCount", "likeCount", "likes", "favorite_count",
              "like_count", "score", "upvotes", "points", "recommendCount"),
    "comments_count": ("commentCount", "commentsCount", "comments_count",
                       "replyCount", "repliesCount", "num_comments", "comments"),
    "shares": ("shareCount", "sharesCount", "retweet_count", "retweetCount",
               "repostCount", "shares"),
    "saves": ("collectCount", "bookmarkCount", "saveCount", "savesCount",
              "boostCount", "saves"),
    "author_followers": ("creatorSubscriberCount", "subscriberCount",
                         "followersCount", "followers_count", "fans",
                         "followerCount"),
}


def _as_int(v: Any) -> Optional[int]:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (list, dict)):
        return len(v) or None
    try:
        n = int(float(str(v).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None
    return n if n >= 0 else None


def extract_engagement(row: dict) -> dict:
    """Pull engagement metrics out of a provider row, whatever it calls them.

    A missing metric stays absent rather than becoming 0: "not reported by this
    platform" and "nobody engaged" are different facts and must not be merged.
    """
    out: dict = {}
    if not isinstance(row, dict):
        return out
    for field_name, aliases in _ENGAGEMENT_ALIASES.items():
        for alias in aliases:
            if alias in row:
                n = _as_int(row[alias])
                if n is not None:
                    out[field_name] = n
                    break
    return out


@dataclass
class RawItem:
    external_id: str
    text: str
    kind: str = "post"                     # post|comment|review|transcript|issue|answer|note
    url: Optional[str] = None
    title: Optional[str] = None
    author_ref: Optional[str] = None       # public handle only; no private PII
    published_at: Optional[str] = None
    extraction_method: str = "api_field"   # read_full|metadata_only|user_supplied|api_field
    raw_meta: dict = field(default_factory=dict)
    # views / likes / comments_count / shares / saves / author_followers
    engagement: dict = field(default_factory=dict)


@dataclass
class FetchResult:
    items: list[RawItem] = field(default_factory=list)
    access_status: str = OK
    http_code: Optional[int] = None
    reason: Optional[str] = None
    endpoint: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.access_status in (OK, PARTIAL)


@dataclass
class Capability:
    """Documented, auditable access facts for the feasibility table."""
    platform: str
    access_mechanism: str
    data_available: str
    credentials_required: list[str]
    limits: str
    tos_notes: str
    needs_human: str = ""


class Connector:
    platform: str = "base"
    capability: Capability

    def available(self) -> tuple[bool, str]:
        """(usable_now, reason_if_not)."""
        missing = [c for c in self.capability.credentials_required if not os.environ.get(c)]
        if missing:
            return False, f"missing credentials: {', '.join(missing)}"
        return True, ""

    # Set by subclasses that can be reachability-tested cheaply.
    probe_url: Optional[str] = None

    def probe(self, timeout: int = 12) -> tuple[bool, str]:
        """Cheap live reachability check. (reachable, reason_if_not).

        Used by the feasibility table so it reports what this container can
        really reach, instead of only whether credentials are present.
        """
        if not self.probe_url:
            return True, ""
        code, err, _ = http_get(self.probe_url, timeout=timeout)
        if err:
            return False, err
        if code and code >= 500:
            return False, f"upstream HTTP {code}"
        return True, ""

    def search(self, query: str, limit: int = 20, **kw: Any) -> FetchResult:
        raise NotImplementedError


def http_get(url: str, params: Optional[dict] = None, headers: Optional[dict] = None,
             timeout: int = 30) -> tuple[Optional[int], Optional[str], Optional[Any]]:
    """GET helper. Returns (http_code, error_reason, parsed_json_or_text).

    Network-policy denials in this sandbox surface as connection errors; they
    are reported as such rather than being silently swallowed.
    """
    import requests

    verify: Any = True
    if os.path.exists(CA_BUNDLE):
        verify = CA_BUNDLE
    try:
        r = requests.get(url, params=params or {}, headers=headers or {},
                         timeout=timeout, verify=verify)
    except requests.exceptions.ProxyError as e:
        return None, f"proxy/network policy denied host: {e.__class__.__name__}", None
    except requests.exceptions.SSLError as e:
        return None, f"tls error: {e}", None
    except requests.exceptions.RequestException as e:
        return None, f"network error: {e.__class__.__name__}: {e}", None
    body: Any
    try:
        body = r.json()
    except Exception:
        body = r.text
    return r.status_code, None, body
