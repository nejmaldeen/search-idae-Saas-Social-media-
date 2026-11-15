import os

import pytest

from oda.connectors import REGISTRY, capability_table, get, searchable_platforms
from oda.connectors.base import (ERROR, NETWORK_BLOCKED, NOT_AUTHORIZED, OK,
                                 Capability, Connector, FetchResult)


def test_every_connector_declares_full_capability_metadata():
    for name, c in REGISTRY.items():
        cap = c.capability
        assert isinstance(cap, Capability)
        assert cap.platform == name
        for field in ("access_mechanism", "data_available", "limits", "tos_notes"):
            assert getattr(cap, field).strip(), f"{name} missing {field}"
        assert isinstance(cap.credentials_required, list)


def test_capability_table_separates_support_from_availability():
    for r in capability_table(probe=False):
        assert r["code_supported"] is True
        assert isinstance(r["usable_now"], bool)
        if not r["usable_now"]:
            assert r["blocked_reason"].strip(), f"{r['platform']} blocked without a reason"


def test_connectors_without_credentials_report_not_authorized_and_return_no_items():
    for name in ("tiktok", "instagram", "x", "g2", "capterra"):
        c = get(name)
        ok, why = c.available()
        assert ok is False and why
        res = c.search("inventory problems")
        assert res.items == [], f"{name} must never fabricate items"
        assert res.access_status == NOT_AUTHORIZED
        assert res.reason


def test_youtube_without_key_is_not_authorized_not_an_error():
    os.environ.pop("YOUTUBE_API_KEY", None)
    res = get("youtube").search("inventory")
    assert res.access_status == NOT_AUTHORIZED and res.items == []
    assert "YOUTUBE_API_KEY" in res.reason


def test_reddit_without_credentials_is_not_authorized():
    for k in ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET"):
        os.environ.pop(k, None)
    res = get("reddit").search("inventory")
    assert res.access_status == NOT_AUTHORIZED and res.items == []


def test_fetchresult_ok_semantics():
    assert FetchResult(access_status=OK).ok is True
    assert FetchResult(access_status="partial").ok is True
    for bad in (NOT_AUTHORIZED, NETWORK_BLOCKED, ERROR):
        assert FetchResult(access_status=bad).ok is False


def test_manual_connector_is_always_available():
    ok, why = get("manual").available()
    assert ok and why == ""


def test_manual_connector_handles_empty_and_garbage_input():
    m = get("manual")
    assert m.parse("").items == []
    assert m.parse("   \n  ").items == []
    res = m.parse("{not valid json at all")
    assert len(res.items) == 1   # falls back to treating it as text


def test_manual_search_does_not_pretend_to_search():
    res = get("manual").search("anything")
    assert res.items == [] and "does not search" in res.reason


def test_searchable_platforms_excludes_manual():
    assert "manual" not in searchable_platforms(probe=False)


def test_base_connector_search_is_abstract():
    class C(Connector):
        platform = "x2"
        capability = Capability("x2", "m", "d", [], "l", "t")
    with pytest.raises(NotImplementedError):
        C().search("q")


@pytest.mark.network
def test_github_connector_returns_real_data_or_an_honest_failure():
    """Live check. Either real items, or a truthful non-ok status - never fake."""
    res = get("github").search('is:issue "inventory" "too expensive"', limit=3)
    if res.ok:
        assert res.items, "ok status must carry items"
        for it in res.items:
            assert it.url and it.url.startswith("https://github.com/")
            assert it.text.strip() and it.external_id.startswith("gh:")
            assert it.extraction_method == "read_full"
    else:
        assert res.reason, "a failure must state a reason"
        assert res.items == []
