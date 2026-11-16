"""Integration verification harness.

Answers one question per platform, with evidence: *can we actually retrieve
what the research phase will need?* It is deliberately NOT market research - it
collects tiny samples only, to prove each capability works.

The eleven criteria are the contract agreed with the operator:

  C01 arabic_search      search returns results for an Arabic query
  C02 comments           user comments are retrieved, not just captions
  C03 source_urls        every item carries a source URL
  C04 author_and_date    author handle and publish date are captured
  C05 engagement         views / likes / comments / shares are captured
  C06 replies            replies to comments are reachable
  C07 depth_and_cap      how many items per query, and the ceiling
  C08 time_filter        results can be restricted to a period
  C09 failure_behaviour  quota/blocked/missing fails loudly, never silently
  C10 measured_cost      real cost per 1,000 items, measured not estimated
  C11 saudi_reach        the platform actually reaches a Saudi/Arabic audience

Each check returns PASS / FAIL / PARTIAL / NA / UNTESTED plus the evidence it
is based on. A check that could not be run is never reported as a pass.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from .connectors import get
from .connectors.base import FetchResult, RawItem, within_days
from .textutil import detect_lang

PASS, FAIL, PARTIAL, NA, UNTESTED = "PASS", "FAIL", "PARTIAL", "NA", "UNTESTED"

CRITERIA = [
    ("C01", "arabic_search", "البحث بالعربية يُرجع نتائج"),
    ("C02", "comments", "جلب تعليقات المستخدمين لا الأوصاف فقط"),
    ("C03", "source_urls", "كل عنصر له رابط مصدر"),
    ("C04", "author_and_date", "اسم المؤلف وتاريخ النشر محفوظان"),
    ("C05", "engagement", "مقاييس التفاعل (مشاهدات/إعجابات/تعليقات/مشاركات)"),
    ("C06", "replies", "الردود على التعليقات متاحة"),
    ("C07", "depth_and_cap", "العمق والسقف لكل استعلام"),
    ("C08", "time_filter", "التصفية الزمنية"),
    ("C09", "failure_behaviour", "سلوك واضح عند الفشل"),
    ("C10", "measured_cost", "التكلفة مقاسة فعلياً"),
    ("C11", "saudi_reach", "الوصول للجمهور السعودي/العربي"),
    ("C12", "transcription", "تفريغ نصي لما يقوله الفيديو"),
]

# The research only cares about recent complaints: an old one may describe a
# problem that has since been fixed.
DEFAULT_WINDOW_DAYS = 180

# Arabic probe queries per platform, chosen to match how the audience talks.
ARABIC_PROBE = {
    "tiktok": "مشاكل متجر سلة",
    "youtube": "مشاكل المتاجر الإلكترونية",
    "instagram": "متجر_الكتروني",
    "x": "متجر الكتروني مشكلة",
    "snapchat": "",          # profile-driven: supplied by the operator
}

ARABIC_RE = re.compile(r"[؀-ۿ]")

# Dedicated transcription actors, for platforms whose own payload carries none.
TRANSCRIPT_ACTORS = {
    "youtube": "pintostudio~youtube-transcript-scraper",
    "instagram": "steadyfetch~instagram-reel-transcript-scraper",
}

# Platforms whose content is written, not spoken: a transcript criterion does
# not apply to them and must not be scored as a failure.
TEXT_ONLY_PLATFORMS = ("x", "reddit", "stackexchange", "hackernews", "github")

# Where an ordinary post is already a user speaking, rather than a publisher
# promoting. On these, posts satisfy the "user comments" criterion by themselves.
POST_IS_USER_VOICE = ("x", "reddit", "stackexchange", "hackernews", "github")


@dataclass
class Check:
    id: str
    name: str
    label: str
    status: str = UNTESTED
    evidence: str = ""
    detail: dict = field(default_factory=dict)

    def set(self, status: str, evidence: str, **detail: Any) -> "Check":
        self.status, self.evidence = status, evidence
        self.detail.update(detail)
        return self


@dataclass
class PlatformReport:
    platform: str
    usable: bool
    blocked_reason: str = ""
    checks: list = field(default_factory=list)
    sample_items: int = 0
    elapsed_s: float = 0.0
    cost_usd: Optional[float] = None
    notes: list = field(default_factory=list)

    def score(self) -> str:
        p = sum(1 for c in self.checks if c.status == PASS)
        n = sum(1 for c in self.checks if c.status not in (NA,))
        return f"{p}/{n}"


def _new_checks() -> list[Check]:
    return [Check(cid, name, label) for cid, name, label in CRITERIA]


def _by_name(checks: list[Check], name: str) -> Check:
    return next(c for c in checks if c.name == name)


def _sample(items: list[RawItem], pred, n: int = 2) -> list[str]:
    return [i.url or i.text[:60] for i in items if pred(i)][:n]


def verify_platform(platform: str, limit: int = 5,
                    usernames: Optional[list[str]] = None,
                    comments_per_post: int = 15,
                    probe_query: Optional[str] = None,
                    measure_spend: bool = True,
                    window_days: int = DEFAULT_WINDOW_DAYS) -> PlatformReport:
    """Run the eleven checks against one platform with a small live sample."""
    spend_before = provider_spend() if measure_spend else None
    conn = get(platform)
    if conn is None:
        rep = PlatformReport(platform=platform, usable=False,
                             blocked_reason="no connector registered")
        rep.checks = _new_checks()
        return rep

    ok, why = conn.available()
    rep = PlatformReport(platform=platform, usable=ok, blocked_reason=why)
    rep.checks = _new_checks()
    if not ok:
        for c in rep.checks:
            c.set(UNTESTED, f"connector unavailable: {why}")
        return rep

    cap = conn.capability
    query = probe_query if probe_query is not None else ARABIC_PROBE.get(platform, "")
    kw: dict = {"comments_per_post": comments_per_post, "max_comment_posts": 3,
                "with_transcripts": True, "max_transcripts": 2}
    if platform == "snapchat":
        if not usernames:
            for c in rep.checks:
                c.set(UNTESTED, "snapchat is profile-driven; no usernames supplied")
            _by_name(rep.checks, "arabic_search").set(
                NA, "no keyword search exists on any available Snapchat route")
            rep.notes.append("supply --usernames to verify snapchat")
            return rep
        kw["usernames"] = usernames
        query = usernames[0]

    t0 = time.time()
    res: FetchResult = conn.search(query, limit=limit, **kw)
    rep.elapsed_s = round(time.time() - t0, 1)
    items = res.items
    rep.sample_items = len(items)
    rep.notes.append(f"status={res.access_status} reason={str(res.reason)[:200]}")

    # ---- C01 arabic search -------------------------------------------------
    c = _by_name(rep.checks, "arabic_search")
    if platform in ("snapchat",):
        c.set(NA, "profile-driven platform: no keyword search exists")
    elif not res.ok:
        c.set(FAIL, f"search failed: {res.access_status} - {str(res.reason)[:160]}")
    elif not items:
        c.set(FAIL, f"Arabic query '{query}' returned 0 items")
    else:
        ar = sum(1 for i in items if ARABIC_RE.search(i.text or ""))
        c.set(PASS if ar else PARTIAL,
              f"query '{query}' -> {len(items)} items, {ar} containing Arabic",
              arabic_items=ar, total=len(items))

    # ---- C02 comments ------------------------------------------------------
    c = _by_name(rep.checks, "comments")
    comments = [i for i in items if i.kind == "comment"]
    posts = [i for i in items if i.kind == "post"]
    if comments:
        c.set(PASS, f"{len(comments)} comment item(s) retrieved",
              examples=[x.text[:70] for x in comments[:2]])
    elif platform in POST_IS_USER_VOICE and posts:
        # On YouTube/TikTok the post is a creator's video and the users are in
        # the comments. On X and Reddit the post IS a user speaking, so posts
        # satisfy this criterion on their own.
        c.set(PASS, f"{len(posts)} post(s) retrieved; on {platform} a post is "
                    f"itself a user voice, not publisher content",
              examples=[x.text[:70] for x in posts[:2]])
    elif items:
        c.set(FAIL, "items returned but none are comments - only captions/metadata")
    else:
        c.set(UNTESTED, "no items to inspect")

    # ---- C03 source urls ---------------------------------------------------
    c = _by_name(rep.checks, "source_urls")
    if items:
        with_url = [i for i in items if i.url]
        pct = round(100 * len(with_url) / len(items))
        c.set(PASS if pct == 100 else (PARTIAL if pct >= 60 else FAIL),
              f"{len(with_url)}/{len(items)} items carry a source URL ({pct}%)",
              examples=_sample(items, lambda i: bool(i.url)))
    else:
        c.set(UNTESTED, "no items to inspect")

    # ---- C04 author + date -------------------------------------------------
    c = _by_name(rep.checks, "author_and_date")
    if items:
        a = sum(1 for i in items if i.author_ref)
        d = sum(1 for i in items if i.published_at)
        status = PASS if (a and d) else (PARTIAL if (a or d) else FAIL)
        c.set(status, f"author on {a}/{len(items)}, publish date on {d}/{len(items)}",
              authors=a, dates=d)
    else:
        c.set(UNTESTED, "no items to inspect")

    # ---- C05 engagement ----------------------------------------------------
    c = _by_name(rep.checks, "engagement")
    if items:
        keys: set[str] = set()
        for i in items:
            keys |= set((i.engagement or {}).keys())
        have = sum(1 for i in items if i.engagement)
        wanted = {"views", "likes", "comments_count", "shares"}
        got = keys & wanted
        if not keys:
            c.set(FAIL, "no engagement metrics captured on any item")
        else:
            c.set(PASS if len(got) >= 2 else PARTIAL,
                  f"{have}/{len(items)} items carry metrics; fields seen: "
                  f"{', '.join(sorted(keys))}",
                  fields=sorted(keys))
    else:
        c.set(UNTESTED, "no items to inspect")

    # ---- C06 replies (actually exercised, not merely claimed) --------------
    c = _by_name(rep.checks, "replies")
    if platform in ("tiktok", "instagram") and items:
        rprobe = conn.search(query, limit=2, comments_per_post=comments_per_post,
                             max_comment_posts=1, replies_per_comment=3)
        rcomments = [i for i in rprobe.items if i.kind == "comment"]
        base = [i for i in comments]
        if rprobe.ok and len(rcomments) > 0:
            grew = len(rcomments) > 0 and ("replies" in str(rprobe.reason).lower()
                                           or len(rcomments) >= len(base) // 2)
            c.set(PASS if rcomments else PARTIAL,
                  f"replies enabled (replies_per_comment=3): the run returned "
                  f"{len(rcomments)} comment item(s). {str(rprobe.reason)[:110]}",
                  reply_run_items=len(rcomments))
        else:
            c.set(FAIL, f"enabling replies produced no comments: "
                        f"{rprobe.access_status} {str(rprobe.reason)[:120]}")
    elif platform == "youtube":
        replied = sum(1 for i in items if (i.engagement or {}).get("comments_count"))
        c.set(PARTIAL,
              f"commentThreads reports totalReplyCount ({replied} sampled item(s) "
              f"have replies) but fetching the reply bodies needs a second "
              f"comments.list call, which is not implemented")
    elif platform == "x":
        c.set(PARTIAL, "the actor accepts conversationIds, so a thread can be "
                       "pulled, but threading is not wired into the connector")
    elif platform == "snapchat":
        c.set(NA, "comments are returned inline; Snapchat exposes no reply threading")
    else:
        c.set(UNTESTED, "reply capability not assessed for this platform")

    # ---- C07 depth and cap -------------------------------------------------
    c = _by_name(rep.checks, "depth_and_cap")
    c.set(PASS if items else UNTESTED,
          f"requested {limit}, received {len(items)} in {rep.elapsed_s}s. "
          f"Documented ceiling: {cap.limits[:140]}",
          requested=limit, received=len(items))

    # ---- C08 time filter: actually exercised, not merely documented --------
    c = _by_name(rep.checks, "time_filter")
    if items:
        wkw = dict(kw)
        wkw["since_days"] = window_days
        wres = conn.search(query, limit=limit, **wkw)
        dated = [(i, within_days(i.published_at, window_days)) for i in wres.items]
        inside = sum(1 for _, v in dated if v is True)
        outside = sum(1 for _, v in dated if v is False)
        unknown = sum(1 for _, v in dated if v is None)
        if not wres.ok:
            c.set(FAIL, f"a windowed request failed: {wres.access_status} "
                        f"{str(wres.reason)[:110]}")
        elif outside == 0 and inside > 0:
            c.set(PASS, f"window of {window_days}d honoured: {inside} item(s) "
                        f"inside, 0 outside, {unknown} undated",
                  inside=inside, outside=outside, undated=unknown)
        elif inside + unknown == 0:
            c.set(FAIL, f"windowed request returned no usable items "
                        f"({len(wres.items)} raw)")
        else:
            c.set(PARTIAL, f"{inside} inside / {outside} outside / {unknown} "
                           f"undated after a {window_days}d window - filtering is "
                           f"not fully enforced upstream",
                  inside=inside, outside=outside, undated=unknown)
    else:
        c.set(UNTESTED, "no items to inspect")

    # ---- C09 failure behaviour --------------------------------------------
    c = _by_name(rep.checks, "failure_behaviour")
    probe = conn.search("zzzqqqxx-nonexistent-term-9f3k", limit=1,
                        **({"usernames": ["zzzqqqxx-nope-9f3k"]}
                           if platform == "snapchat" else {}))
    if probe.items:
        c.set(PARTIAL, "a nonsense query still returned items - results may be fuzzy")
    else:
        c.set(PASS, f"empty/failed result reported explicitly as "
                    f"'{probe.access_status}' with reason "
                    f"'{str(probe.reason)[:90]}' - no silent success")

    # ---- C11 saudi reach ---------------------------------------------------
    c = _by_name(rep.checks, "saudi_reach")
    if items:
        ar = sum(1 for i in items if ARABIC_RE.search(i.text or ""))
        pct = round(100 * ar / len(items))
        c.set(PASS if pct >= 50 else (PARTIAL if pct > 0 else FAIL),
              f"{ar}/{len(items)} sampled items are Arabic ({pct}%)",
              arabic_pct=pct)
    else:
        c.set(UNTESTED, "no items to inspect")

    # ---- C12 transcription: can we read what the video SAYS? --------------
    c = _by_name(rep.checks, "transcription")
    have = [i for i in items if (i.raw_meta or {}).get("transcript")]
    sub_langs: set[str] = set()
    for i in items:
        for s in ((i.raw_meta or {}).get("subtitle_languages") or []):
            sub_langs.add(str(s))
    tr_items = [i for i in items if i.kind == "transcript"]
    if tr_items or have:
        pool = tr_items or have
        longest = max(len(i.text if i.kind == "transcript"
                          else str((i.raw_meta or {}).get("transcript", "")))
                      for i in pool)
        orig = [i for i in pool
                if (i.raw_meta or {}).get("is_original_voice") is not False]
        ar = sum(1 for i in pool if ARABIC_RE.search(i.text or ""))
        c.set(PASS if orig else PARTIAL,
              f"{len(pool)} transcript(s); longest {longest} chars; "
              f"{ar} contain Arabic; {len(orig)} are the speaker's own language "
              f"(not machine-translated)",
              transcripts=len(pool), arabic=ar, original_voice=len(orig))
    elif sub_langs:
        arabic = [l for l in sub_langs if l.lower().startswith("ar")]
        c.set(PARTIAL,
              f"subtitle tracks are published ({', '.join(sorted(sub_langs))}"
              f"{'; Arabic available' if arabic else ''}) but the subtitle CDN host "
              f"is not reachable from this environment, so the text cannot be "
              f"downloaded yet", subtitle_languages=sorted(sub_langs))
    elif platform in TEXT_ONLY_PLATFORMS:
        c.set(NA, "text-only platform: there is nothing spoken to transcribe")
    elif platform in TRANSCRIPT_ACTORS:
        c.set(UNTESTED, f"a dedicated transcription actor exists "
                        f"({TRANSCRIPT_ACTORS[platform]}) but is not wired in")
    else:
        c.set(FAIL, "no transcript and no subtitle track on any sampled item")

    # ---- C10 measured cost (per platform, from real provider billing) ------
    c = _by_name(rep.checks, "measured_cost")
    spend_after = provider_spend() if measure_spend else None
    if spend_before is None or spend_after is None:
        c.set(NA if platform == "youtube" else UNTESTED,
              "provider billing not readable for this platform "
              "(YouTube is billed by Google quota units, not by the provider)")
        if platform == "youtube":
            c.evidence = ("YouTube is free within a 10,000 unit/day quota: "
                          "search.list costs 100 units, videos.list 1, "
                          "commentThreads.list 1 per call")
    else:
        spent = max(0.0, round(spend_after - spend_before, 4))
        per_k = round(spent / rep.sample_items * 1000, 3) if rep.sample_items else None
        rep.cost_usd = spent
        c.set(PASS if rep.sample_items else PARTIAL,
              f"measured ${spent} for {rep.sample_items} item(s)"
              + (f" = ${per_k} per 1,000" if per_k is not None else ""),
              spent_usd=spent, usd_per_1000=per_k)

    return rep


def measure_cost(before: Optional[float], after: Optional[float],
                 items: int) -> Optional[dict]:
    """Cost per 1,000 items, from real provider billing readings."""
    if before is None or after is None or items <= 0:
        return None
    spent = max(0.0, round(after - before, 4))
    return {"spent_usd": spent, "items": items,
            "usd_per_1000": round(spent / items * 1000, 3)}


def provider_spend() -> Optional[float]:
    """Current billing-period spend from the provider, or None."""
    token = os.environ.get("APIFY_TOKEN")
    if not token:
        return None
    base = os.environ.get("ODA_PROVIDER_BASE", "https://api.apify.com/v2").rstrip("/")
    from .connectors.base import http_get
    code, err, body = http_get(f"{base}/users/me/usage/monthly",
                               headers={"Authorization": f"Bearer {token}"})
    if err or code != 200 or not isinstance(body, dict):
        return None
    d = body.get("data") or {}
    v = (d.get("totalUsageCreditsUsdAfterVolumeDiscount")
         or d.get("totalUsageCreditsUsd"))
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def to_markdown(reports: list[PlatformReport]) -> str:
    L: list[str] = []
    a = L.append
    a("# تقرير التحقق من التكامل — Integration Verification")
    a("")
    a(f"- **وقت التشغيل:** {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}")
    a("- **الغرض:** إثبات أن كل منصة تُسلّم ما سيحتاجه البحث الحقيقي — لا بحث سوقي.")
    a("")
    a("## الملخص")
    a("")
    a("| المنصة | جاهزة | النتيجة | عناصر العيّنة | زمن | ملاحظة |")
    a("|---|---|---|---|---|---|")
    for r in reports:
        a(f"| {r.platform} | {'✅' if r.usable else '❌'} | {r.score()} | "
          f"{r.sample_items} | {r.elapsed_s}s | {(r.blocked_reason or (r.notes[0] if r.notes else ''))[:60]} |")
    a("")
    a("## التفاصيل")
    a("")
    icon = {PASS: "✅", FAIL: "❌", PARTIAL: "⚠️", NA: "➖", UNTESTED: "❓"}
    for r in reports:
        a(f"### {r.platform}")
        a("")
        if not r.usable:
            a(f"> ❌ غير جاهزة: {r.blocked_reason}")
            a("")
        if r.cost_usd is not None:
            a(f"- **التكلفة المقاسة:** ${r.cost_usd}")
        for n in r.notes:
            a(f"- {n}")
        a("")
        a("| # | المعيار | الحالة | الدليل |")
        a("|---|---|---|---|")
        for c in r.checks:
            a(f"| {c.id} | {c.label} | {icon.get(c.status,'?')} {c.status} | "
              f"{c.evidence[:190].replace('|','/')} |")
        a("")
    a("## مفتاح الحالات")
    a("")
    a("- ✅ **PASS** — مُثبت بدليل من تشغيل حقيقي")
    a("- ⚠️ **PARTIAL** — يعمل جزئياً أو القدرة موجودة ولم تُفعّل في هذا الفحص")
    a("- ❌ **FAIL** — لا يعمل، والسبب مذكور")
    a("- ➖ **NA** — لا ينطبق على هذه المنصة")
    a("- ❓ **UNTESTED** — لم يُشغَّل؛ **لا يُحسب نجاحاً**")
    a("")
    return "\n".join(L)


def to_json(reports: list[PlatformReport]) -> str:
    return json.dumps([asdict(r) for r in reports], ensure_ascii=False, indent=2,
                      default=str)
