"""Bilingual (AR/EN) query expansion engine.

Produces explicit, logged query strings per platform. Templates are
illustrative scaffolding for *searching* — never treated as market evidence.
"""
from __future__ import annotations

from typing import Iterable, Optional

from . import db
from .textutil import detect_lang, normalize

# --- intent templates -------------------------------------------------------
# {d} = domain term, {m} = market/locale term

PAIN_AR = [
    "مشاكل {d}",
    "مشكلة في {d}",
    "تعبت من {d}",
    "صعوبة في {d}",
    "أضيع وقت في {d}",
    "يستهلك وقت {d}",
    "معاناة {d}",
    "{d} معقد",
    "{d} مكلف",
]
PAIN_EN = [
    "{d} problems",
    "{d} pain points",
    "struggling with {d}",
    "{d} is time consuming",
    "wasting time on {d}",
    "{d} too expensive",
    "frustrated with {d}",
    "{d} manual process",
]
ALTERNATIVE_AR = [
    "بديل {d}",
    "هل يوجد بديل {d}",
    "أفضل برنامج {d}",
    "برنامج لإدارة {d}",
]
ALTERNATIVE_EN = [
    "alternatives to {d}",
    "{d} alternative",
    "best {d} software",
    "{d} tool recommendation",
    "switching from {d}",
]
HELP_AR = [
    "أحتاج حل {d}",
    "كيف أدير {d}",
    "نصائح {d}",
    "أتمنى لو توجد أداة {d}",
]
HELP_EN = [
    "how do you handle {d}",
    "i wish there was a tool for {d}",
    "need a solution for {d}",
    "any way to automate {d}",
]
FEATURE_EN = [
    "{d} feature request",
    "{d} missing feature",
    "{d} does not support",
]
FEATURE_AR = [
    "{d} لا يدعم",
    "ميزة ناقصة {d}",
]

# Sector synonym seeds. Extend per domain; kept small and explicit.
SYNONYMS: dict[str, dict[str, list[str]]] = {
    "ecommerce": {
        # Includes how the platforms are really written in Arabic comments
        # (transliterations and short forms), which is where the domain signal
        # actually lives in colloquial text.
        "ar": ["متجر إلكتروني", "التجارة الإلكترونية", "إدارة المخزون", "متابعة الطلبات",
               "خدمة العملاء", "الشيبينج", "المرتجعات", "تسعير المنتجات",
               "سلة", "زد", "شوبيفاي", "شبوفاي", "ووكومرس", "أمازون", "نون",
               "دروبشيبينج", "الدفع", "الشحن", "المنتجات", "الطلبات", "المخزون",
               "متجري", "البيع اونلاين", "علي اكسبرس", "باي بال", "مدى"],
        "en": ["ecommerce store", "online store", "inventory management", "order management",
               "customer support", "shipping fulfillment", "returns handling", "product pricing"],
    },
    "saas": {
        "ar": ["اشتراكات", "لوحة تحكم", "تقارير", "فواتير"],
        "en": ["subscription billing", "dashboard reporting", "invoicing", "churn"],
    },
}

# Terms that make a domain word mean something else. "متجر" means both an
# e-commerce store and an app store; without this, Google Play and Android TV
# comments are mistaken for merchant pain. Declared per sector, not hard-coded
# into the extractor, so each project can state its own homonym traps.
SECTOR_EXCLUSIONS = {
    "ecommerce": [
        "جوجل بلاي", "جوجل بلي", "قوقل بلاي", "متجر التطبيقات", "متجر بلاي",
        "اندرويد", "أندرويد", "سمارت تي في", "شاشه", "شاشة", "تلفزيون",
        "لعبه", "لعبة", "ابتويد",
        "google play", "play store", "app store", "android tv", "smart tv",
        "aptoide", "playstore", "appstore", "firestick", "apk",
    ],
    "saas": [],
}


def exclusions_for(sector: Optional[str]) -> list[str]:
    return SECTOR_EXCLUSIONS.get((sector or "").strip().lower(), [])


# Market-local phrasing hints (not evidence; search aids only).
MARKETS: dict[str, dict[str, list[str]]] = {
    "sa": {"ar": ["السعودية", "سلة", "زد"], "en": ["saudi", "ksa", "salla", "zid"]},
    "ae": {"ar": ["الإمارات", "دبي"], "en": ["uae", "dubai"]},
    "eg": {"ar": ["مصر"], "en": ["egypt"]},
}

# Where the target audience actually talks. Searching all of Reddit for
# "inventory problems" returns noise; searching the business subreddits returns
# store owners. Same idea for Stack Exchange: softwarerecs is literally people
# asking "I need a tool that does X", which is the highest-signal site for
# opportunity discovery.
SECTOR_SUBREDDITS = {
    "ecommerce": ["ecommerce", "shopify", "smallbusiness", "Entrepreneur",
                  "dropship", "woocommerce", "FulfillmentByAmazon"],
    "saas": ["SaaS", "startups", "Entrepreneur", "smallbusiness", "msp"],
}
DEFAULT_SUBREDDITS = ["smallbusiness", "Entrepreneur"]

SECTOR_SE_SITES = {
    "ecommerce": ["softwarerecs", "webmasters", "magento"],
    "saas": ["softwarerecs", "serverfault"],
}
DEFAULT_SE_SITES = ["softwarerecs"]


def subreddits_for(sector: Optional[str]) -> list[str]:
    return SECTOR_SUBREDDITS.get((sector or "").strip().lower(), DEFAULT_SUBREDDITS)


def se_sites_for(sector: Optional[str]) -> list[str]:
    return SECTOR_SE_SITES.get((sector or "").strip().lower(), DEFAULT_SE_SITES)


# Measured against the live APIs: softwarerecs.stackexchange returns 0 results
# for any query over 2 words, because these endpoints AND every term together.
# Hacker News tolerates 3. Narrow platforms therefore get the bare domain term
# and rely on the extraction layer to find the pain, instead of encoding the
# pain in a query that matches nothing.
TIGHT_PLATFORMS = {"stackexchange", "hackernews"}


def render_for_platform(text: str, platform: str, term: Optional[str] = None) -> str:
    """Platform-specific rendering of a query string."""
    if platform == "github":
        # GitHub full-text search: quote multi-word phrases so "wish there was"
        # matches as a phrase instead of as loose terms.
        words = text.split()
        if len(words) > 1 and '"' not in text:
            return f'"{text}"'
    if platform in TIGHT_PLATFORMS and term:
        return " ".join(term.split()[:3])
    return text


HASHTAG_SEEDS = {
    "ar": ["#متاجر_الكترونية", "#تجارة_الكترونية", "#ريادة_اعمال"],
    "en": ["#ecommerce", "#shopify", "#smallbusiness", "#saas"],
}

# Primary content language per platform. Query execution is ordered so a
# platform's dominant language runs first; running Arabic complaint queries
# against an English-dominant developer platform wastes the rate-limit budget.
PLATFORM_PRIMARY_LANGS = {
    "github": ["en"],
    "hackernews": ["en"],
    "stackexchange": ["en"],
    "reddit": ["en"],
    "youtube": ["ar", "en"],
    "tiktok": ["ar", "en"],
    "instagram": ["ar", "en"],
    "x": ["ar", "en"],
    "manual": ["ar", "en"],
}


def lang_priority(platform: str, lang: str) -> int:
    """0 = primary language for this platform, 1 = secondary."""
    return 0 if lang in PLATFORM_PRIMARY_LANGS.get(platform, ["en", "ar"]) else 1


# Which intents each platform's search realistically supports.
PLATFORM_INTENTS = {
    "github": ["pain", "help", "feature", "alternative"],
    "hackernews": ["pain", "alternative", "help"],
    "stackexchange": ["pain", "help", "feature"],
    "reddit": ["pain", "alternative", "help", "feature"],
    "youtube": ["pain", "help", "alternative"],
    "tiktok": ["pain", "help", "hashtag"],
    "instagram": ["hashtag"],
    "x": ["pain", "alternative", "hashtag"],
    "manual": ["pain", "alternative", "help", "feature", "hashtag"],
}

_TEMPLATES = {
    ("pain", "ar"): PAIN_AR, ("pain", "en"): PAIN_EN,
    ("alternative", "ar"): ALTERNATIVE_AR, ("alternative", "en"): ALTERNATIVE_EN,
    ("help", "ar"): HELP_AR, ("help", "en"): HELP_EN,
    ("feature", "ar"): FEATURE_AR, ("feature", "en"): FEATURE_EN,
}


# Keyword-search APIs (HN/Algolia, Stack Exchange, Reddit) AND all terms
# together, so a long domain phrase matches nothing. Queries are built from
# short noun phrases instead of the full domain sentence.
MAX_TERM_WORDS = 3
_STOPWORDS_EN = {"and", "or", "the", "for", "of", "in", "a", "an", "with", "to"}


def _shorten(phrase: str) -> list[str]:
    """Turn a long domain sentence into usable short noun phrases."""
    words = [w for w in phrase.split() if w.lower() not in _STOPWORDS_EN]
    if not words:
        return []
    if len(words) <= MAX_TERM_WORDS:
        return [" ".join(words)]
    # sliding pairs keep the meaningful combinations ("inventory management",
    # "order management") instead of one unusable 6-word string
    out = [" ".join(words[i:i + 2]) for i in range(len(words) - 1)]
    return out[:4]


def _domain_terms(domain: str, languages: Iterable[str],
                  sector: Optional[str] = None) -> dict[str, list[str]]:
    """Base terms per language: short domain phrases plus curated synonyms."""
    out: dict[str, list[str]] = {lang: [] for lang in languages}
    dl = detect_lang(domain)
    for lang in out:
        if dl == lang or dl in ("mixed", "unknown"):
            out[lang].extend(_shorten(domain.strip()))
    key = (sector or "").strip().lower()
    if key in SYNONYMS:
        for lang in out:
            out[lang].extend(SYNONYMS[key].get(lang, []))
    # Never leave a language empty: fall back to the literal domain.
    for lang in out:
        if not out[lang]:
            out[lang].append(domain.strip())
    # de-dup preserving order
    for lang in out:
        seen, uniq = set(), []
        for t in out[lang]:
            n = normalize(t)
            if n and n not in seen:
                seen.add(n)
                uniq.append(t)
        out[lang] = uniq
    return out


def expand(domain: str, languages: Iterable[str] = ("ar", "en"),
           sector: Optional[str] = None, market: Optional[str] = None,
           platforms: Iterable[str] = ("manual",),
           competitor_names: Iterable[str] = (),
           max_per_platform: int = 40) -> list[dict]:
    """Return a list of dicts: {text, lang, platform, intent}."""
    languages = [l for l in languages if l in ("ar", "en")] or ["en"]
    terms = _domain_terms(domain, languages, sector)
    mk = MARKETS.get((market or "").strip().lower(), {})

    out: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(text: str, lang: str, platform: str, intent: str,
            term: Optional[str] = None) -> None:
        text = " ".join(text.split())
        if not text:
            return
        key = (normalize(text), platform)
        if key in seen:
            return
        seen.add(key)
        out.append({"text": text, "lang": lang, "platform": platform,
                    "intent": intent, "term": term})

    for platform in platforms:
        allowed = PLATFORM_INTENTS.get(platform, ["pain"])
        # An English-only platform cannot answer Arabic queries; planning them
        # only burns the rate-limit/quota budget.
        plat_langs = PLATFORM_PRIMARY_LANGS.get(platform, ["ar", "en"])
        platform_languages = [l for l in languages if l in plat_langs] or list(languages)
        # Budget is split evenly across languages so one language cannot
        # starve the other (bilingual coverage is a hard requirement).
        per_lang = max(1, max_per_platform // max(1, len(platform_languages)))
        for lang in platform_languages:
            used = 0
            # Round-robin over intents, then templates, so every intent is
            # represented before any single intent exhausts the budget.
            buckets = []
            for intent in allowed:
                tpls = _TEMPLATES.get((intent, lang), [])
                for term in terms[lang][:4]:
                    for tpl in tpls:
                        buckets.append((intent, tpl.format(d=term), term))
            by_intent: dict[str, list[tuple[str, str]]] = {}
            for intent, text, term in buckets:
                by_intent.setdefault(intent, []).append((text, term))
            while used < per_lang and any(by_intent.values()):
                for intent in list(by_intent):
                    if used >= per_lang:
                        break
                    if not by_intent[intent]:
                        continue
                    text, term = by_intent[intent].pop(0)
                    before = len(out)
                    add(text, lang, platform, intent, term=term)
                    if len(out) > before:
                        used += 1
            # market-flavoured variants
            for loc in mk.get(lang, [])[:2]:
                for term in terms[lang][:2]:
                    add(f"{term} {loc}", lang, platform, "generic", term=term)
            # hashtags only where the platform uses them
            if "hashtag" in allowed:
                for h in HASHTAG_SEEDS.get(lang, []):
                    add(h, lang, platform, "hashtag", term=h)
        # competitor/tool names
        for name in competitor_names:
            if "alternative" in allowed:
                add(f"{name} alternative", "en", platform, "alternative", term=name)
                add(f"بديل {name}", "ar", platform, "alternative", term=name)
            if "pain" in allowed:
                add(f"{name} problems", "en", platform, "pain", term=name)
    return out


def persist(conn, project_id: str, queries: list[dict], run_id: Optional[str] = None) -> list[str]:
    """Insert queries idempotently (UNIQUE project+text+platform). Returns ids."""
    ids = []
    for q in queries:
        qid = db.new_id("q")
        cur = conn.execute(
            "INSERT INTO search_queries(id,project_id,run_id,text,lang,platform,intent,term,"
            "status,created_at) VALUES(?,?,?,?,?,?,?,?, 'planned', ?)"
            " ON CONFLICT(project_id,text,platform) DO NOTHING",
            (qid, project_id, run_id, q["text"], q["lang"], q["platform"], q.get("intent"),
             q.get("term"), db.now()),
        )
        if cur.rowcount:
            ids.append(qid)
        else:
            row = db.one(conn, "SELECT id FROM search_queries WHERE project_id=? AND text=? AND platform=?",
                         (project_id, q["text"], q["platform"]))
            if row:
                ids.append(row["id"])
    conn.commit()
    return ids


def list_queries(conn, project_id: str, platform: Optional[str] = None,
                 status: Optional[str] = None) -> list:
    sql = "SELECT * FROM search_queries WHERE project_id=?"
    params: list = [project_id]
    if platform:
        sql += " AND platform=?"
        params.append(platform)
    if status:
        sql += " AND status=?"
        params.append(status)
    sql += " ORDER BY platform, intent, lang"
    out = db.rows(conn, sql, params)
    if platform:
        out.sort(key=lambda r: (lang_priority(platform, r["lang"]), r["intent"] or ""))
    return out
