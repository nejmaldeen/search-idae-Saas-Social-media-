"""Commercial-provider connector: input shaping, output mapping, error paths.

These run offline. Provider actors return wildly different field names, so the
mapper is the part most likely to break silently - it is tested against real
response shapes from each actor family.
"""
import json
import os

import pytest

from oda.connectors import PROVIDER_BACKED, capability_table, refresh_registry
from oda.connectors.base import (ERROR, NETWORK_BLOCKED, NOT_AUTHORIZED, OK,
                                 RATE_LIMITED)
from oda.connectors.provider import (DEFAULT_ACTORS, INPUT_BUILDERS,
                                     ProviderConnector, _CAPS, map_item)


@pytest.fixture()
def conn_tiktok():
    return ProviderConnector("tiktok", _CAPS["tiktok"])


# ----------------------------------------------------------------- mapping
def test_maps_tiktok_comment_shape():
    row = {"cid": "7312", "text": "I waste hours renaming product images",
           "webVideoUrl": "https://www.tiktok.com/@x/video/1", "uniqueId": "merchant1",
           "createTimeISO": "2026-02-01T10:00:00Z", "diggCount": 42, "replyCount": 3}
    it = map_item(row, "tiktok")
    assert it.external_id == "tiktok:7312"
    assert "renaming product images" in it.text
    assert it.url.startswith("https://www.tiktok.com/")
    assert it.author_ref == "merchant1"
    assert it.published_at == "2026-02-01T10:00:00Z"
    assert it.extraction_method == "read_full"
    # engagement now lives in its own typed field, not buried in raw_meta
    assert it.engagement["likes"] == 42
    assert it.engagement["comments_count"] == 3


def test_maps_instagram_shape():
    row = {"id": "ig99", "text": "this tool is too expensive for a small store",
           "ownerUsername": "shopowner", "timestamp": "2026-03-05T08:00:00Z",
           "postUrl": "https://instagram.com/p/abc", "likesCount": 7}
    it = map_item(row, "instagram")
    assert it.external_id == "ig99" or it.external_id == "instagram:ig99"
    assert it.author_ref == "shopowner"
    assert it.url == "https://instagram.com/p/abc"


def test_maps_reddit_shape_with_nested_author():
    row = {"id": "r1", "title": "Inventory sync is broken",
           "selftext": "We reconcile stock by hand every week.",
           "author": {"name": "u_merchant"}, "permalink": "https://reddit.com/r/x/1",
           "created_utc": "1762000000", "score": 12, "num_comments": 4}
    it = map_item(row, "reddit")
    assert it.author_ref == "u_merchant"          # nested dict resolved
    assert it.engagement["comments_count"] == 4
    assert it.engagement["likes"] == 12            # reddit score maps to likes
    assert it.url == "https://reddit.com/r/x/1"


def test_maps_x_shape():
    row = {"tweetId": "t5", "fullText": "looking for an alternative to our POS",
           "screen_name": "owner", "createdAt": "2026-04-01", "likeCount": 2}
    it = map_item(row, "x")
    assert it.external_id == "x:t5"
    assert "alternative" in it.text


def test_rows_without_text_are_skipped_not_invented():
    assert map_item({"id": "1", "likesCount": 5}, "tiktok") is None
    assert map_item({"id": "2", "text": "   "}, "tiktok") is None
    assert map_item("not a dict", "tiktok") is None


def test_mapper_never_fabricates_an_id():
    """A row with text but no id gets a content-derived id, never a random one."""
    row = {"text": "stable text", "url": "https://e.invalid/1"}
    a = map_item(row, "tiktok")
    b = map_item(dict(row), "tiktok")
    assert a.external_id == b.external_id


# ----------------------------------------------------------- input builders
def test_every_provider_platform_has_an_input_builder_and_actor():
    for name in PROVIDER_BACKED:
        assert name in INPUT_BUILDERS, f"{name} has no input builder"
        assert DEFAULT_ACTORS.get(name), f"{name} has no default actor"


def test_input_builders_carry_the_query_and_limit():
    blob = json.dumps(INPUT_BUILDERS["tiktok"]("inventory pain", 25))
    assert "inventory pain" in blob and "25" in blob
    blob = json.dumps(INPUT_BUILDERS["reddit"]("inventory pain", 10))
    assert "inventory pain" in blob


# ------------------------------------------------------------- error paths
def test_no_token_is_not_authorized_and_returns_nothing(conn_tiktok, monkeypatch):
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    res = conn_tiktok.search("inventory")
    assert res.access_status == NOT_AUTHORIZED
    assert res.items == []
    assert "APIFY_TOKEN" in res.reason


class _Resp:
    def __init__(self, code, payload=None, text=""):
        self.status_code, self._p, self.text = code, payload, text

    def json(self):
        if self._p is None:
            raise ValueError("no json")
        return self._p


def _patch_post(monkeypatch, resp):
    import requests
    monkeypatch.setattr(requests, "post", lambda *a, **k: resp)


def test_deprecated_actor_404_says_how_to_fix(conn_tiktok, monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "t")
    _patch_post(monkeypatch, _Resp(404, text="not found"))
    res = conn_tiktok.search("x")
    assert res.access_status == ERROR and res.http_code == 404
    assert "ODA_ACTOR_TIKTOK" in res.reason   # actionable, names the override


def test_bad_token_reported_as_not_authorized(conn_tiktok, monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "bad")
    _patch_post(monkeypatch, _Resp(401))
    res = conn_tiktok.search("x")
    assert res.access_status == NOT_AUTHORIZED and res.items == []


def test_quota_exhaustion_reported_as_rate_limited(conn_tiktok, monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "t")
    _patch_post(monkeypatch, _Resp(429))
    res = conn_tiktok.search("x")
    assert res.access_status == RATE_LIMITED


def test_blocked_host_reported_as_network_blocked(conn_tiktok, monkeypatch):
    import requests
    monkeypatch.setenv("APIFY_TOKEN", "t")

    def boom(*a, **k):
        raise requests.exceptions.ProxyError("denied")

    monkeypatch.setattr(requests, "post", boom)
    res = conn_tiktok.search("x")
    assert res.access_status == NETWORK_BLOCKED
    assert "not allowed" in res.reason


def test_successful_run_maps_rows(conn_tiktok, monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "t")
    _patch_post(monkeypatch, _Resp(200, [
        {"cid": "1", "text": "we track stock in excel and it breaks", "uniqueId": "a"},
        {"cid": "2", "likesCount": 3},                      # no text -> skipped
        {"cid": "3", "text": "too expensive for us", "uniqueId": "b"},
    ]))
    res = conn_tiktok.search("inventory", limit=5)
    assert res.ok and len(res.items) == 2
    assert "skipped=1" in res.reason
    assert {i.author_ref for i in res.items} == {"a", "b"}


def test_non_json_response_is_an_error_not_a_crash(conn_tiktok, monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "t")
    _patch_post(monkeypatch, _Resp(200, None, text="<html>"))
    res = conn_tiktok.search("x")
    assert res.access_status == ERROR and res.items == []


def test_actor_is_overridable_by_env(monkeypatch):
    c = ProviderConnector("reddit", _CAPS["reddit"])
    assert c.actor == DEFAULT_ACTORS["reddit"]
    monkeypatch.setenv("ODA_ACTOR_REDDIT", "someone~new-actor")
    assert c.actor == "someone~new-actor"


# ------------------------------------------------------------ registry swap
def test_registry_uses_stub_without_token_and_provider_with_token(monkeypatch):
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    rows = {r["platform"]: r for r in capability_table()}
    for name in PROVIDER_BACKED:
        assert rows[name]["usable_now"] is False
        assert rows[name]["blocked_reason"]

    monkeypatch.setenv("APIFY_TOKEN", "t")
    rows = {r["platform"]: r for r in capability_table()}
    for name in PROVIDER_BACKED:
        assert rows[name]["usable_now"] is True, name
        assert "provider" in rows[name]["access_mechanism"].lower()


def test_provider_capabilities_document_why_no_official_path():
    for name in ("tiktok", "reddit"):
        notes = _CAPS[name].tos_notes.lower()
        assert "official" in notes
        assert _CAPS[name].credentials_required == ["APIFY_TOKEN"]


def test_comment_rows_inherit_the_parent_post_url():
    """A comment's provenance is its parent post; evidence must never be url-less."""
    row = {"cid": "99", "text": "the mid plan will not let me add staff",
           "videoWebUrl": "https://www.tiktok.com/@a/video/1",
           "uniqueId": "merchant", "createTimeISO": "2026-01-01T00:00:00Z"}
    it = map_item(row, "tiktok")
    assert it.url == "https://www.tiktok.com/@a/video/1"
    assert it.author_ref == "merchant"


def test_nested_author_container_is_resolved():
    row = {"id": "1", "text": "stock sync keeps breaking",
           "authorMeta": {"name": "soladig2", "nickName": "سولا"}}
    assert map_item(row, "tiktok").author_ref == "soladig2"


def test_instagram_builder_turns_a_bare_query_into_a_hashtag_url():
    """`search` returns hashtag metadata, not posts - directUrls is required."""
    out = INPUT_BUILDERS["instagram"]("ecommerce", 10)
    assert "directUrls" in out
    assert out["directUrls"][0].endswith("/explore/tags/ecommerce")
    assert out["resultsType"] == "posts"
    passthru = INPUT_BUILDERS["instagram"]("https://www.instagram.com/p/X", 5)
    assert passthru["directUrls"] == ["https://www.instagram.com/p/X"]


def test_reddit_builder_uses_the_documented_field_names():
    out = INPUT_BUILDERS["reddit"]("inventory sync", 10)
    assert out["queries"] == ["inventory sync"]      # not "searches"
    assert out["maxItems"] == 10


def test_operating_systems_are_not_treated_as_competitors():
    """'Win7' leaked in from Hacker News OS threads; it is not a market rival."""
    from oda.competitors import extract_candidates
    found = extract_candidates("Win8 has no alternative to the win7 recent programs list")
    assert not found
    # a genuine product still survives the filter
    assert "Zoho" in " ".join(extract_candidates("alternatives to Zoho Inventory"))


# --------------------------------------------------- engagement + snapchat
def test_engagement_distinguishes_missing_from_zero():
    """'Not reported by this platform' and 'nobody engaged' are different facts."""
    from oda.connectors.base import extract_engagement
    assert extract_engagement({"text": "x"}) == {}          # absent -> absent
    assert extract_engagement({"diggCount": 0}) == {"likes": 0}   # zero -> kept


def test_engagement_normalises_every_platforms_field_names():
    from oda.connectors.base import extract_engagement
    tiktok = extract_engagement({"diggCount": 42, "playCount": 2215,
                                 "shareCount": 7, "collectCount": 3,
                                 "commentCount": 9})
    assert tiktok == {"views": 2215, "likes": 42, "comments_count": 9,
                      "shares": 7, "saves": 3}
    snap = extract_engagement({"viewCount": 15000, "shareCount": 12,
                               "commentCount": 30, "boostCount": 5,
                               "creatorSubscriberCount": 4090400})
    assert snap["views"] == 15000 and snap["author_followers"] == 4090400
    assert extract_engagement({"likesCount": 88})["likes"] == 88


def test_engagement_survives_dirty_values():
    from oda.connectors.base import extract_engagement
    out = extract_engagement({"viewCount": "1,234", "diggCount": "n/a",
                              "shareCount": None, "commentCount": True})
    assert out == {"views": 1234}


def test_snapchat_is_profile_driven_not_keyword_driven():
    """No Snapchat actor supports keyword search; the builder must not pretend."""
    from oda.connectors.provider import PROFILE_ONLY
    assert "snapchat" in PROFILE_ONLY
    out = INPUT_BUILDERS["snapchat"]("@somestore", 10)
    assert out["usernames"] == ["somestore"]        # @ stripped
    assert "searchQueries" not in out and "queries" not in out
    assert out["includeTranscripts"] is True        # transcripts are the big win
    explicit = INPUT_BUILDERS["snapchat"]("ignored", 5, usernames=["a", "b"])
    assert explicit["usernames"] == ["a", "b"]


def test_snapchat_capability_states_the_no_search_limit_plainly():
    notes = (_CAPS["snapchat"].limits + _CAPS["snapchat"].needs_human).lower()
    assert "no keyword search" in notes
    assert "monitoring" in _CAPS["snapchat"].limits.lower()


# ---------------------------------------------------- silent-failure guard
def test_sentinel_rows_are_not_reported_as_a_successful_empty_result():
    """apidojo~tweet-scraper answers with {"noResults": true} rows. Mapping
    those away silently would report 'ok, 0 items' and hide a real block."""
    from oda.connectors.provider import is_sentinel_row
    assert is_sentinel_row({"noResults": True}) == "noResults=True"
    assert is_sentinel_row({"error": "rate limited"}) == "error=rate limited"
    assert is_sentinel_row({"text": "a real tweet"}) is None
    # a row carrying text wins even if it also has an error field
    assert is_sentinel_row({"text": "real", "error": "partial"}) is None
    assert is_sentinel_row("not a dict") is None


def test_all_sentinel_response_surfaces_as_error(conn_tiktok, monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "t")
    _patch_post(monkeypatch, _Resp(200, [{"noResults": True}, {"noResults": True}]))
    res = conn_tiktok.search("anything")
    assert res.access_status == ERROR, "must not look like a successful empty page"
    assert res.items == []
    assert "noResults" in res.reason and "no results" in res.reason.lower()


def test_mixed_sentinel_and_content_is_partial_not_silent(conn_tiktok, monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "t")
    _patch_post(monkeypatch, _Resp(200, [
        {"noResults": True},
        {"cid": "1", "text": "we reconcile stock by hand", "uniqueId": "a"},
    ]))
    res = conn_tiktok.search("inventory")
    assert len(res.items) == 1
    assert "marker_rows=1" in res.reason      # the marker is reported, not hidden


def test_posts_with_zero_comments_are_not_sent_to_the_comments_actor(conn_tiktok, monkeypatch):
    """Paying an actor to fetch comments from posts that have none is waste."""
    monkeypatch.setenv("APIFY_TOKEN", "t")
    calls = []

    class _R:
        status_code = 200

        def __init__(self, payload):
            self._p = payload

        def json(self):
            return self._p

    def fake_post(url, **kw):
        import json as _j
        body = _j.loads(kw.get("data") or "{}")
        calls.append((url, body))
        if "comments" in url:
            return _R([{"cid": "c1", "text": "this plan will not let me add staff",
                        "videoWebUrl": "https://tt/1"}])
        return _R([
            {"cid": "1", "text": "post with talk", "webVideoUrl": "https://tt/1",
             "commentCount": 12},
            {"cid": "2", "text": "post with silence", "webVideoUrl": "https://tt/2",
             "commentCount": 0},
        ])

    import requests
    monkeypatch.setattr(requests, "post", fake_post)
    res = conn_tiktok.search("inventory", limit=2)
    assert res.ok
    comment_calls = [b for u, b in calls if "comments" in u]
    assert comment_calls, "the comments actor should still run"
    sent = comment_calls[0]["postURLs"]
    assert sent == ["https://tt/1"], f"the silent post must be skipped, got {sent}"
