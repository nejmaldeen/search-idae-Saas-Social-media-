from oda import db
from oda.queries import expand, lang_priority, list_queries, persist


def test_expand_is_bilingual_and_balanced():
    # youtube hosts both languages, so both must be planned and balanced
    qs = expand("ecommerce inventory", languages=("ar", "en"), sector="ecommerce",
                market="sa", platforms=("youtube",))
    langs = {q["lang"] for q in qs}
    assert langs == {"ar", "en"}
    ar = sum(1 for q in qs if q["lang"] == "ar")
    en = sum(1 for q in qs if q["lang"] == "en")
    # neither language may be starved
    assert ar > 0 and en > 0
    assert min(ar, en) / max(ar, en) > 0.4


def test_expand_covers_multiple_intents():
    qs = expand("inventory", languages=("en",), platforms=("reddit",))
    intents = {q["intent"] for q in qs}
    assert {"pain", "alternative", "help"} <= intents


def test_expand_includes_competitor_terms():
    qs = expand("inventory", languages=("en",), platforms=("reddit",),
                competitor_names=["Zoho Inventory"])
    texts = " | ".join(q["text"] for q in qs)
    assert "Zoho Inventory alternative" in texts


def test_persist_is_idempotent(conn, project):
    qs = expand("inventory", languages=("en",), platforms=("github",))
    first = persist(conn, project, qs)
    second = persist(conn, project, qs)
    assert len(first) == len(qs)
    # re-persisting returns the same ids, creates no new rows
    assert sorted(first) == sorted(second)
    total = db.one(conn, "SELECT COUNT(*) FROM search_queries WHERE project_id=?", (project,))[0]
    assert total == len(qs)


def test_language_priority_matches_platform():
    assert lang_priority("github", "en") == 0
    assert lang_priority("github", "ar") == 1
    assert lang_priority("youtube", "ar") == 0


def test_list_queries_orders_primary_language_first(conn, project):
    persist(conn, project, expand("inventory", languages=("ar", "en"), platforms=("github",)))
    rows = list_queries(conn, project, platform="github")
    assert rows[0]["lang"] == "en"   # github is English-dominant


def test_github_queries_are_phrase_quoted():
    from oda.queries import render_for_platform
    assert render_for_platform("wish there was a tool", "github") == '"wish there was a tool"'
    assert render_for_platform("inventory", "github") == "inventory"       # single word untouched
    assert render_for_platform("inventory problems", "reddit") == "inventory problems"


def test_sector_targeting_picks_business_communities():
    from oda.queries import se_sites_for, subreddits_for
    subs = subreddits_for("ecommerce")
    assert "shopify" in subs and "smallbusiness" in subs
    assert "softwarerecs" in se_sites_for("ecommerce")
    # unknown sector still returns a usable default, never empty
    assert subreddits_for(None) and se_sites_for("nonsense")


def test_english_only_platforms_are_not_given_arabic_queries():
    """Arabic queries on an English-only platform only burn quota."""
    for platform in ("github", "hackernews", "stackexchange"):
        qs = expand("ecommerce inventory", languages=("ar", "en"),
                    sector="ecommerce", platforms=(platform,))
        assert qs, f"{platform} must still get queries"
        assert {q["lang"] for q in qs} == {"en"}, platform


def test_tight_platforms_get_short_queries():
    """Measured: softwarerecs returns nothing for queries over ~2 words."""
    from oda.queries import render_for_platform
    qs = expand("ecommerce inventory and order management", languages=("en",),
                sector="ecommerce", platforms=("stackexchange",))
    for q in qs:
        rendered = render_for_platform(q["text"], "stackexchange", q.get("term"))
        assert len(rendered.split()) <= 3, f"too long for this API: {rendered!r}"


def test_every_query_carries_its_source_term():
    qs = expand("ecommerce inventory", languages=("en",), sector="ecommerce",
                platforms=("stackexchange",), competitor_names=["Cin7"])
    assert all(q.get("term") for q in qs)


def test_long_domain_is_shortened_into_usable_phrases():
    from oda.queries import _shorten
    out = _shorten("ecommerce inventory and order management")
    assert all(len(p.split()) <= 3 for p in out)
    assert "order management" in out
