"""Transcript service: routing, provenance, and the joining of segments.

Offline. The point of these tests is that a transcript's *provenance* is kept:
a machine translation is a paraphrase and must never be mistaken for the
speaker's own words.
"""
import pytest

from oda.transcripts import (DEFAULT_TRANSCRIPT_ACTORS, TRANSCRIPT_INPUTS,
                             Transcript, _join_segments, has_language,
                             transcript_for_item)


def test_inline_transcript_is_used_without_paying_a_provider(monkeypatch):
    """Snapchat already returns the text; nothing should be fetched."""
    def explode(*a, **k):
        raise AssertionError("must not call the provider when text is inline")

    import oda.transcripts as T
    monkeypatch.setattr(T, "fetch_transcript", explode)
    t = transcript_for_item("snapchat", "https://snap/1",
                            raw_meta={"transcript": "المتحدث يشرح مشاكل الشحن"})
    assert t.ok and t.source == "inline"
    assert "مشاكل" in t.text


def test_no_url_is_reported_not_guessed():
    t = transcript_for_item("youtube", None)
    assert not t.ok and "no url" in t.reason


def test_has_language_prefers_the_first_requested():
    tracks = [{"language": "en", "track_kind": "asr"},
              {"language": "ar", "track_kind": "asr"}]
    assert has_language(tracks, ("ar", "en")) == "ar"
    assert has_language(tracks, ("en", "ar")) == "en"
    assert has_language(tracks, ("fr",)) is None
    assert has_language([], ("ar",)) is None


def test_segments_join_and_drop_rolling_duplicates():
    """YouTube repeats each caption line as it scrolls; duplicates must go."""
    rows = [{"data": [
        {"text": "من اهم عوامل النجاح"},
        {"text": "من اهم عوامل النجاح"},     # rolling repeat
        {"text": "في التجاره الالكترونيه"},
    ]}]
    text, n = _join_segments(rows)
    assert n == 2
    assert text == "من اهم عوامل النجاح في التجاره الالكترونيه"


def test_join_handles_plain_strings_and_empties():
    assert _join_segments([]) == ("", 0)
    assert _join_segments(["  "]) == ("", 0)
    assert _join_segments(["hello", "world"]) == ("hello world", 2)


def test_translated_transcript_is_not_treated_as_the_speakers_voice():
    original = Transcript("نص عربي", is_translated=False, original_language="ar")
    translated = Transcript("english text", is_translated=True, original_language="ar")
    assert original.is_original_voice is True
    assert translated.is_original_voice is False
    assert Transcript("").is_original_voice is False


def test_youtube_actor_can_actually_return_arabic():
    """The popular pintostudio actor only emits en/pt/es/fr/de/it, so it can
    never return Arabic. Guard against silently regressing to it."""
    assert DEFAULT_TRANSCRIPT_ACTORS["youtube"] != "pintostudio~youtube-transcript-scraper"
    payload = TRANSCRIPT_INPUTS["youtube"]("https://youtu.be/x", "ar")
    assert payload["language"] == "ar"
    assert payload["videoUrls"] == ["https://youtu.be/x"]


def test_missing_provider_token_is_reported_not_silent(monkeypatch):
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    from oda.transcripts import fetch_transcript
    t = fetch_transcript("youtube", "https://youtu.be/x")
    assert not t.ok and "APIFY_TOKEN" in t.reason


def test_unknown_platform_has_no_actor_and_says_so(monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "t")
    from oda.transcripts import fetch_transcript
    t = fetch_transcript("myspace", "https://x/1")
    assert not t.ok and "no transcript actor" in t.reason
