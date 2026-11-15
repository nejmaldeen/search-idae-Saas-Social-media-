"""Language detection, Arabic/English normalization, hashing, shingles."""
from __future__ import annotations

import hashlib
import re
import unicodedata

ARABIC_RE = re.compile(r"[؀-ۿݐ-ݿ]")
LATIN_RE = re.compile(r"[A-Za-z]")

# Arabic diacritics (harakat) + tatweel
_DIACRITICS = re.compile(r"[ؗ-ًؚ-ْٰۖ-ۭـ]")
_PUNCT = re.compile(r"[^\w\s؀-ۿ]", re.UNICODE)
_WS = re.compile(r"\s+")


def detect_lang(text: str) -> str:
    """Coarse language tag: 'ar', 'en', 'mixed' or 'unknown'."""
    if not text:
        return "unknown"
    ar = len(ARABIC_RE.findall(text))
    la = len(LATIN_RE.findall(text))
    if ar == 0 and la == 0:
        return "unknown"
    if ar and la:
        ratio = ar / (ar + la)
        if 0.2 < ratio < 0.8:
            return "mixed"
        return "ar" if ratio >= 0.8 else "en"
    return "ar" if ar else "en"


def normalize_arabic(text: str) -> str:
    text = _DIACRITICS.sub("", text)
    text = re.sub(r"[آأإٱ]", "ا", text)  # alef variants -> alef
    text = text.replace("ى", "ي")                        # alef maksura -> ya
    text = text.replace("ة", "ه")                        # ta marbuta -> ha
    text = re.sub(r"[ؤ]", "و", text)                      # waw hamza -> waw
    return text


def normalize(text: str) -> str:
    """Normalization used for hashing / similarity. Lossy on purpose."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.lower()
    text = normalize_arabic(text)
    text = _PUNCT.sub(" ", text)
    return _WS.sub(" ", text).strip()


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


def short_hash(text: str, n: int = 16) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:n]


def tokens(text: str) -> list[str]:
    return [t for t in normalize(text).split() if len(t) > 1]


def shingles(text: str, k: int = 4) -> set[str]:
    """Word-level k-shingles; falls back to the token set for short texts."""
    tk = tokens(text)
    if len(tk) < k:
        return set(tk)
    return {" ".join(tk[i:i + k]) for i in range(len(tk) - k + 1)}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if not inter:
        return 0.0
    return inter / len(a | b)


def token_overlap(a: str, b: str) -> float:
    """Containment-biased similarity, better than Jaccard for uneven lengths."""
    ta, tb = set(tokens(a)), set(tokens(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def snippet(text: str, limit: int = 400) -> str:
    text = _WS.sub(" ", (text or "").strip())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
