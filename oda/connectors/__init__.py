"""Connector registry."""
from __future__ import annotations

from .base import (DENIED, ERROR, NETWORK_BLOCKED, NOT_AUTHORIZED, OK, PARTIAL,
                   RATE_LIMITED, Capability, Connector, FetchResult, RawItem)
from .github_issues import GitHubIssuesConnector
from .hackernews import HackerNewsConnector
from .manual_import import ManualImportConnector
from .reddit import RedditConnector
from .stackexchange import StackExchangeConnector
from .provider import build_provider_connectors
from .unavailable import (CapterraConnector, G2Connector, InstagramConnector,
                          SnapchatConnector, TikTokConnector, XConnector)
from .youtube import YouTubeConnector

_CLASSES = [
    ManualImportConnector, GitHubIssuesConnector, HackerNewsConnector,
    StackExchangeConnector, RedditConnector, YouTubeConnector,
    TikTokConnector, InstagramConnector, XConnector, SnapchatConnector,
    G2Connector, CapterraConnector,
]

REGISTRY: dict[str, Connector] = {c.platform: c() for c in _CLASSES}
_PROBE_CACHE: dict[str, tuple[bool, str]] = {}

# Platforms with no official self-serve path for a commercial operator are
# served by the commercial-provider connector instead of the "unavailable"
# stub. The stub stays in place until a provider token is configured, so the
# feasibility table never claims access the operator does not have.
PROVIDER_BACKED = ("tiktok", "instagram", "x", "reddit", "snapchat", "g2", "capterra")

# The platforms where the Saudi audience actually is. Verification and
# collection effort is focused here; the technical English-language sources
# (github / hackernews / stackexchange) still work but are out of scope.
SAUDI_PRIORITY = ("snapchat", "tiktok", "x", "youtube", "instagram")


def refresh_registry() -> dict[str, Connector]:
    """Re-resolve provider-backed platforms against the current environment."""
    providers = build_provider_connectors()
    for name in PROVIDER_BACKED:
        prov = providers.get(name)
        if prov is None:
            continue
        ok, _ = prov.available()
        if ok:
            REGISTRY[name] = prov
        elif name not in REGISTRY or isinstance(REGISTRY.get(name), type(prov)):
            # fall back to the honest stub when no token is configured
            stub = {c.platform: c for c in _CLASSES}.get(name)
            if stub is not None:
                REGISTRY[name] = stub()
    _PROBE_CACHE.clear()
    return REGISTRY


def get(platform: str) -> Connector | None:
    if platform in PROVIDER_BACKED:
        refresh_registry()
    return REGISTRY.get(platform)


def capability_table(probe: bool = False, use_cache: bool = True) -> list[dict]:
    """Feasibility audit table, computed live from each connector.

    With probe=True each networked connector is reachability-tested, so the
    table distinguishes "credentials missing" from "host blocked here".
    """
    refresh_registry()
    out = []
    for name, c in REGISTRY.items():
        ok, why = c.available()
        if ok and probe and getattr(c, "probe_url", None):
            if use_cache and name in _PROBE_CACHE:
                reachable, preason = _PROBE_CACHE[name]
            else:
                reachable, preason = c.probe()
                _PROBE_CACHE[name] = (reachable, preason)
            if not reachable:
                ok, why = False, f"host not reachable from this environment: {preason}"
        cap = c.capability
        out.append({
            "platform": name,
            "access_mechanism": cap.access_mechanism,
            "data_available": cap.data_available,
            "credentials_required": ", ".join(cap.credentials_required) or "none",
            "limits": cap.limits,
            "tos_notes": cap.tos_notes,
            "needs_human": cap.needs_human,
            "code_supported": True,
            "usable_now": ok,
            "blocked_reason": why,
        })
    return out


def searchable_platforms(probe: bool = False) -> list[str]:
    return [r["platform"] for r in capability_table(probe=probe)
            if r["usable_now"] and r["platform"] != "manual"]
