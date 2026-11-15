"""Transcript service: read what a video actually SAYS.

A caption is mostly hashtags. The spoken content is where the complaint is, so
this module is what makes video sources usable at all.

Routes, in cost order (verified live 2026-11-15):

1. **Already in the payload** — Snapchat returns `transcript` inline and TikTok
   returns an AI summary. Free, nothing to do.
2. **Official availability check** — YouTube `captions.list` needs only an API
   key and reveals whether an Arabic track exists (`trackKind=asr`). It cannot
   download the text (that needs the video owner's OAuth), but it is the cheap
   way to avoid paying to transcribe a video that has no Arabic track.
3. **Provider actor** — returns the actual text. Billed per run, so it is only
   invoked for videos step 2 says are worth it.

Why not a local library: `youtube-transcript-api` and `yt-dlp` are free and
would be the obvious choice, but they fetch from youtube.com, which this
environment's network policy blocks (verified: HTTP 000). The provider actor
runs on the provider's own infrastructure, so it is unaffected.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Optional

from .connectors.base import CA_BUNDLE, http_get

CAPTIONS = "https://www.googleapis.com/youtube/v3/captions"

# Provider actors that return transcript text, per platform.
DEFAULT_TRANSCRIPT_ACTORS = {
    # fit_melon is used over the more popular pintostudio actor because the
    # latter's targetLanguage enum is ['en','pt','es','fr','de','it'] - it
    # cannot return Arabic at all, only a machine translation into English.
    # fit_melon returns the ORIGINAL track and reports isTranslated /
    # originalLanguage, which is what makes the text usable as evidence.
    "youtube": "fit_melon~youtube-transcript-scraper",
    "instagram": "steadyfetch~instagram-reel-transcript-scraper",
}

# Each actor takes its own input shape; built from their published schemas.
TRANSCRIPT_INPUTS = {
    "youtube": lambda url, lang: {"videoUrls": [url], "language": lang},
    "instagram": lambda url, lang: {"directUrls": [url]},
}


@dataclass
class Transcript:
    text: str
    language: Optional[str] = None
    source: str = ""              # inline | actor:<id> | none
    segments: int = 0
    available_languages: list = field(default_factory=list)
    reason: str = ""
    # Provenance that decides how far the text can be trusted as evidence:
    # a machine translation is a paraphrase, not the speaker's own words.
    is_translated: Optional[bool] = None
    is_auto_generated: Optional[bool] = None
    original_language: Optional[str] = None

    @property
    def ok(self) -> bool:
        return bool(self.text and self.text.strip())

    @property
    def is_original_voice(self) -> bool:
        """True only when the text is the speaker's own language, untranslated."""
        return self.ok and self.is_translated is not True


def caption_tracks(video_id: str, api_key: Optional[str] = None) -> tuple[list[dict], str]:
    """Official, cheap availability check. Returns (tracks, reason).

    Costs 50 quota units of YouTube's 10,000/day. Use it to skip videos with no
    usable track before paying a provider to transcribe them.
    """
    key = api_key or os.environ.get("YOUTUBE_API_KEY")
    if not key:
        return [], "missing YOUTUBE_API_KEY"
    code, err, body = http_get(CAPTIONS, params={
        "part": "snippet", "videoId": video_id, "key": key})
    if err:
        return [], f"network error: {err}"
    if code != 200 or not isinstance(body, dict):
        msg = (body or {}).get("error", {}).get("message", "") if isinstance(body, dict) else ""
        return [], f"HTTP {code}: {msg[:120]}"
    tracks = []
    for it in body.get("items", []):
        sn = it.get("snippet") or {}
        tracks.append({"language": sn.get("language"),
                       "track_kind": sn.get("trackKind"),
                       "name": sn.get("name")})
    return tracks, ""


def has_language(tracks: list[dict], prefixes: tuple[str, ...] = ("ar", "en")) -> Optional[str]:
    """First track whose language matches one of `prefixes`, in that order."""
    for want in prefixes:
        for t in tracks:
            lang = (t.get("language") or "").lower()
            if lang.startswith(want):
                return t.get("language")
    return None


def _join_segments(rows: Any) -> tuple[str, int]:
    """Actors return either a flat string or timestamped segments. Consecutive
    duplicate lines are dropped: YouTube's rolling captions repeat each line."""
    segs: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, str):
            if node.strip():
                segs.append(node.strip())
        elif isinstance(node, dict):
            for k in ("text", "transcript", "caption", "line"):
                if isinstance(node.get(k), str) and node[k].strip():
                    segs.append(node[k].strip())
                    return
            for v in node.values():
                if isinstance(v, (list, dict)):
                    walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(rows)
    deduped: list[str] = []
    for s in segs:
        if not deduped or deduped[-1] != s:
            deduped.append(s)
    return " ".join(deduped), len(deduped)


def fetch_transcript(platform: str, url: str, language: str = "ar",
                     timeout: int = 180) -> Transcript:
    """Fetch transcript text through the provider. Costs money per run."""
    token = os.environ.get("APIFY_TOKEN")
    if not token:
        return Transcript("", source="none", reason="missing APIFY_TOKEN")
    actor = os.environ.get(f"ODA_TRANSCRIPT_ACTOR_{platform.upper()}",
                           DEFAULT_TRANSCRIPT_ACTORS.get(platform, ""))
    builder = TRANSCRIPT_INPUTS.get(platform)
    if not actor or builder is None:
        return Transcript("", source="none",
                          reason=f"no transcript actor configured for {platform}")

    base = os.environ.get("ODA_PROVIDER_BASE", "https://api.apify.com/v2").rstrip("/")
    import requests
    verify: Any = CA_BUNDLE if os.path.exists(CA_BUNDLE) else True
    try:
        r = requests.post(
            f"{base}/acts/{actor}/run-sync-get-dataset-items",
            params={"timeout": timeout, "memory": 1024},
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"},
            data=json.dumps(builder(url, language)),
            timeout=timeout + 30, verify=verify)
    except requests.exceptions.RequestException as e:
        return Transcript("", source=f"actor:{actor}",
                          reason=f"network error: {e.__class__.__name__}")
    if r.status_code >= 400:
        return Transcript("", source=f"actor:{actor}",
                          reason=f"HTTP {r.status_code}: {r.text[:140]}")
    try:
        rows = r.json()
    except ValueError:
        return Transcript("", source=f"actor:{actor}", reason="non-JSON response")

    first = rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else {}
    # Prefer the actor's own joined text when it provides one; it preserves
    # sentence order better than re-joining segments.
    text = first.get("transcriptText") if isinstance(first.get("transcriptText"), str) else ""
    n = len(first.get("segments") or []) if isinstance(first.get("segments"), list) else 0
    if not text.strip():
        text, n = _join_segments(rows)
    if not text.strip():
        return Transcript("", source=f"actor:{actor}", segments=0,
                          reason=f"actor returned no transcript text "
                                 f"(status={first.get('status', 'unknown')})")
    langs = [l.get("languageCode") for l in (first.get("availableLanguages") or [])
             if isinstance(l, dict) and l.get("languageCode")]
    return Transcript(
        text=text.strip(),
        language=first.get("transcriptLanguage") or language,
        source=f"actor:{actor}", segments=n,
        available_languages=langs,
        is_translated=first.get("isTranslated"),
        is_auto_generated=first.get("isAutoGenerated"),
        original_language=first.get("originalLanguage"))


def transcript_for_item(platform: str, url: Optional[str],
                        raw_meta: Optional[dict] = None,
                        video_id: Optional[str] = None,
                        want: tuple[str, ...] = ("ar", "en"),
                        check_availability: bool = True) -> Transcript:
    """Full resolution path for one item, cheapest route first."""
    raw_meta = raw_meta or {}

    # 1. already inline - free
    inline = raw_meta.get("transcript")
    if isinstance(inline, str) and inline.strip():
        return Transcript(text=inline.strip(),
                          source=raw_meta.get("transcript_source") or "inline",
                          segments=1)

    if not url:
        return Transcript("", source="none", reason="no url to transcribe")

    # 2. official availability check before paying (YouTube only)
    langs: list = []
    if platform == "youtube" and check_availability and video_id:
        tracks, why = caption_tracks(video_id)
        langs = [t["language"] for t in tracks if t.get("language")]
        if tracks and not has_language(tracks, want):
            return Transcript("", source="none", available_languages=langs,
                              reason=f"no {'/'.join(want)} caption track "
                                     f"(available: {', '.join(langs) or 'none'})")
        if not tracks and why:
            # availability unknown; fall through and try anyway
            pass
        elif not tracks:
            return Transcript("", source="none", reason="video has no caption tracks")

    # 3. pay the provider for the text
    t = fetch_transcript(platform, url, language=(want[0] if want else "ar"))
    if langs and not t.available_languages:
        t.available_languages = langs
    return t
