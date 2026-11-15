"""Platforms with no authorized programmatic access from this container.

These connectors exist so the system can (a) show an honest capability table,
(b) log an access failure with a reason, and (c) raise a human task that routes
the work to the manual-import path. They never return fabricated items and
never attempt scraping, CAPTCHA bypass or logged-in session reuse.
"""
from __future__ import annotations

from typing import Any

from .base import NOT_AUTHORIZED, Capability, Connector, FetchResult

_SPECS = [
    dict(
        platform="tiktok",
        access_mechanism="TikTok Research API / Display API (application + approval required)",
        data_available="Research API: video metadata, comments, keyword search (approved academics/orgs only)",
        credentials_required=["TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET"],
        limits="Research API is gated by application review; Display API only reads the authorizing user's own content.",
        tos_notes="Scraping the web/app surface violates TikTok ToS. No bypass performed.",
        needs_human="Apply for Research API access, or export/copy content manually.",
    ),
    dict(
        platform="instagram",
        access_mechanism="Instagram Graph API (Business/Creator account + Facebook app review)",
        data_available="Own account media/comments; hashtag search is limited and quota-capped; no arbitrary public comment reads",
        credentials_required=["IG_ACCESS_TOKEN", "IG_BUSINESS_ACCOUNT_ID"],
        limits="30 unique hashtags per 7 days; no public user content search.",
        tos_notes="No scraping of Reels/comments. No bypass performed.",
        needs_human="Connect a Business account + app review, or import manually.",
    ),
    dict(
        platform="x",
        access_mechanism="X API v2 (paid tiers; Basic tier required for search)",
        data_available="Recent search (7 days) on paid tiers; full archive on Enterprise",
        credentials_required=["X_BEARER_TOKEN"],
        limits="Free tier has no search endpoint. Basic tier is rate- and volume-capped.",
        tos_notes="Scraping x.com is prohibited. No bypass performed.",
        needs_human="Supply a paid-tier bearer token, or import manually.",
    ),
    dict(
        platform="snapchat",
        access_mechanism="No official public-content API. Snap exposes Marketing API (ads), "
                         "Snap Kit / Login Kit, and an OAuth-gated Public Profile API.",
        data_available="None programmatically without a commercial provider.",
        credentials_required=["APIFY_TOKEN"],
        limits="No keyword search exists on any available route; collection is profile-driven.",
        tos_notes="No scraping performed by this system; a commercial provider does the "
                  "collection when configured.",
        needs_human="Supply APIFY_TOKEN and the list of accounts to monitor.",
    ),
    dict(
        platform="g2",
        access_mechanism="No public read API. Partner/paid data feeds only.",
        data_available="None programmatically.",
        credentials_required=["G2_PARTNER_TOKEN"],
        limits="N/A",
        tos_notes="robots.txt + ToS disallow automated collection. No scraping performed.",
        needs_human="Review in a browser and paste relevant low-star reviews via manual import.",
    ),
    dict(
        platform="capterra",
        access_mechanism="No public read API (Gartner Digital Markets).",
        data_available="None programmatically.",
        credentials_required=["CAPTERRA_TOKEN"],
        limits="N/A",
        tos_notes="ToS disallow automated collection. No scraping performed.",
        needs_human="Review in a browser and paste relevant reviews via manual import.",
    ),
]


def _make(spec: dict) -> type:
    cap = Capability(**spec)

    class _C(Connector):
        platform = spec["platform"]
        capability = cap

        def search(self, query: str, limit: int = 20, **kw: Any) -> FetchResult:
            ok, why = self.available()
            reason = why or ("no authorized programmatic access available; "
                             "use the manual-import path")
            return FetchResult(access_status=NOT_AUTHORIZED, reason=reason,
                               endpoint=cap.access_mechanism)

    _C.__name__ = spec["platform"].capitalize() + "Connector"
    return _C


_BY_PLATFORM = {spec["platform"]: _make(spec) for spec in _SPECS}

TikTokConnector = _BY_PLATFORM["tiktok"]
InstagramConnector = _BY_PLATFORM["instagram"]
XConnector = _BY_PLATFORM["x"]
SnapchatConnector = _BY_PLATFORM["snapchat"]
G2Connector = _BY_PLATFORM["g2"]
CapterraConnector = _BY_PLATFORM["capterra"]
