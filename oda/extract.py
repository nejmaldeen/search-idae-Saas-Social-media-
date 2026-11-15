"""Pain-Point Intelligence Engine: extract problem signals from text.

Default extractor is deterministic and rule-based ('rules:v1') so the system
works with zero API keys and its decisions are auditable. An LLM layer can be
plugged in (see oda/llm.py); when used, signals are tagged 'llm:<model>' so
generative output is never mistaken for an independent source of fact.

Guards against false positives:
  * a phrase match alone is not enough - the surrounding sentence is kept and
    scored, and `clarity` drops when no domain/tool context term co-occurs;
  * questions that merely contain a trigger word score low;
  * matches inside quoted marketing copy ('we solve X!') are down-weighted.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

from . import db
from .quality import REJECT, WEAK, assess
from .textutil import normalize, normalize_arabic, short_hash, snippet

# ---------------------------------------------------------------- patterns
# Each entry: (pain_type, weight, compiled regex)
_P: list[tuple[str, float, str]] = [
    # --- desire / missing tool
    ("missing_tool", 1.0, r"أتمنى لو|اتمنى لو|يا ريت (?:يكون|في|يوجد)|لو في (?:اداه|أداة|برنامج)|نفسي (?:في|يكون)"),
    ("missing_tool", 1.0, r"\bi wish (?:there (?:was|were)|we had|it)\b|\bwould love (?:a|an|to have)\b|\bif only there\b"),
    ("missing_tool", 0.9, r"\bis there (?:any|a) (?:tool|app|way|software|service)\b|\bdoes anything exist\b"),
    ("missing_tool", 0.9, r"هل (?:يوجد|فيه|في) (?:أداة|اداه|برنامج|تطبيق|حل|طريقة)"),
    # --- time drain
    ("time_drain", 1.0, r"أضيع|اضيع|يضيع وقت|ضايع وقت|ياخذ وقت|يأخذ وقت|يستهلك وقت|وقت طويل|ساعات (?:في|على)"),
    ("time_drain", 1.0, r"\bwast(?:e|ing|es) (?:a lot of )?(?:time|hours)\b|\btakes (?:me|us) (?:\d+|hours|forever|ages)\b|\bspend(?:ing)? (?:\d+ )?hours\b|\btime[- ]consuming\b"),
    # --- manual workaround
    ("manual_workaround", 1.0, r"يدوي|يدويا|بشكل يدوي|أدخل بالي?د|انسخ و?ألصق|نسخ ولصق|على الاكسل|في اكسل|جدول اكسل"),
    ("manual_workaround", 1.0, r"\bmanual(?:ly)?\b|\bcopy[- ]past(?:e|ing)\b|\bby hand\b|\bspreadsheet\b|\bexcel sheet\b|\bgoogle sheet\b"),
    # --- cost
    ("cost", 1.0, r"مكلف|غالي|غالية|سعره? مرتفع|ما أقدر أدفع|لا أستطيع تحمل|اسعار مبالغ"),
    ("cost", 1.0, r"\btoo expensive\b|\bcan'?t afford\b|\boverpriced\b|\bpricing is (?:crazy|insane|ridiculous|too high)\b|\bcosts? (?:too much|a fortune)\b"),
    # --- missing feature
    ("missing_feature", 1.0, r"لا يدعم|ما يدعم|غير مدعوم|مش مدعوم|غير متاح|مش متاح|"
                              r"ما فيه خيار|لا يوجد خيار|ناقص ميزة|ميزة ناقصة|ما يسمح|"
                              r"ما يتوفر|غير متوفر"),
    ("missing_feature", 1.0, r"\bdoes(?:n'?t| not) support\b|\bno way to\b|\bthere'?s no option\b|\bmissing (?:feature|support)\b|\bcan'?t (?:export|import|sync|filter|customi[sz]e)\b"),
    ("missing_feature", 0.8, r"\bfeature request\b|\bwould be (?:great|nice) if\b"),
    # --- alternative seeking
    ("alternative_seeking", 1.0, r"بديل|بدائل|أبحث عن برنامج|افضل برنامج|أفضل أداة"),
    ("alternative_seeking", 1.0, r"\balternative(?:s)? to\b|\blooking for (?:an? )?(?:alternative|replacement)\b|\bswitch(?:ing|ed)? (?:away )?from\b|\bmigrat(?:e|ing) (?:away )?from\b"),
    # --- frustration
    ("frustration", 0.8, r"محبط|مزعج|كارثة|معاناة|تعبت من|زهقت|مشكلة كبيرة|صعب جدا"),
    ("frustration", 0.8, r"\bfrustrat(?:ed|ing)\b|\bnightmare\b|\bpainful\b|\ba huge pain\b|\bdriving me (?:crazy|nuts)\b|\bhate (?:that|how|using)\b"),
    # --- unmet help request
    ("help_request", 0.7, r"كيف\s+(?:أ|ا|ي|ن|ت)\w*|وش الحل|ايش الحل|وش السبب|ايش السبب|"
                          r"أحتاج مساعدة|احتاج حل|ليش ما|ليه ما|لماذا لا\s+\w+"),
    ("help_request", 0.7, r"\bhow (?:do|can) (?:you|i|we)\b|\bany (?:recommendations|suggestions|advice)\b|\bwhat do you (?:use|guys use)\b"),
    # --- colloquial Gulf / Egyptian complaint forms seen in real comments
    ("frustration", 0.85, r"تعقيد(?:ات)?|معقد|صعب (?:جدا|مره|مرة|اوي)|مو واضح|مش واضح|"
                          r"ما فهمت|مش فاهم|لخبطة|دوخة|تهقوة|قهر"),
    ("missing_feature", 0.85, r"ما يطلع|ما يظهر|ما يشتغل|مش شغال|ما ينفع|مش بيشتغل|"
                              r"ما يقبل|مش بيقبل|ما يوافق"),
    ("reliability", 0.85, r"خربان|معطل|يفصل|ينقطع|يختفي|ضاع|ضاعت|اختفت|تكرار الطلبات"),
    ("cost", 0.85, r"غلا|الغلاء|عمولة عالية|عمولات|رسوم عالية|يأكل الربح|ياكل الربح|"
                   r"ما يستاهل السعر"),
    ("help_request", 0.75, r"وش اسوي|ايش اسوي|شلون|ازاي|إزاي|ممكن حد يساعد|محتاج حد"),
    # --- reliability / data integrity
    ("reliability", 0.9, r"يتعطل|يعلق|يخطئ|أخطاء كثيرة|بيانات خاطئة|لا يتزامن|ما يتزامن"),
    ("reliability", 0.9, r"\bkeeps? (?:crashing|breaking|failing)\b|\bout of sync\b|\bwrong (?:data|numbers|stock)\b|\bduplicate (?:orders|records)\b|\bdata loss\b"),
]
PATTERNS = [(t, w, re.compile(rx, re.IGNORECASE | re.UNICODE)) for t, w, rx in _P]

# willingness-to-pay language. Presence = a *signal*, never proof of payment.
WTP = re.compile(
    r"مستعد (?:أدفع|ادفع)|بدفع|راح أدفع|أدفع شهري|ندفع (?:شهري|سنوي)|"
    r"\bwilling to pay\b|\bi(?:'d| would) pay\b|\bhappy to pay\b|\bworth paying\b|"
    r"\bwe pay\b|\bcurrently pay(?:ing)?\b|\b(?:\$|usd|sar|aed)\s?\d+\s?(?:/|per )?(?:mo|month|year)\b",
    re.IGNORECASE | re.UNICODE)

# quantified impact: a number next to a time or money unit
IMPACT = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(ساع(?:ة|ات)|دقيق(?:ة|ائق)|يوم|أيام|اسبوع|أسبوع|شهر|ريال|درهم|دولار|%|"
    r"hours?|hrs?|minutes?|mins?|days?|weeks?|months?|percent|\$|usd|sar|aed)",
    re.IGNORECASE | re.UNICODE)

SEGMENTS = {
    "store_owner": r"صاحب متجر|أصحاب المتاجر|تاجر|متجري|store owner|shop owner|merchant|ecommerce owner|seller",
    "agency": r"وكالة|أعمل مع عملاء|agency|freelanc|consultant|client work",
    "developer": r"مبرمج|مطور|developer|engineer|devops|\bapi\b|sdk",
    "ops_manager": r"مدير العمليات|مدير مخزون|operations manager|warehouse manager|inventory manager|fulfilment|fulfillment",
    "marketer": r"مسوق|التسويق|marketer|marketing team|growth",
    "finance": r"محاسب|مالية|accountant|bookkeep|finance team|cfo",
    "support": r"خدمة العملاء|دعم فني|support (?:agent|team)|customer service",
    "smb": r"شركة صغيرة|مشروع صغير|small business|smb|startup|solo",
}
SEGMENTS = {k: re.compile(v, re.IGNORECASE | re.UNICODE) for k, v in SEGMENTS.items()}

# generic tool-ish context words; a match with none of these is weaker evidence
CONTEXT_HINT = re.compile(
    r"أداة|برنامج|تطبيق|نظام|منصة|لوحة|اشتراك|سوفت|"
    r"\btool\b|\bapp\b|\bsoftware\b|\bplatform\b|\bsystem\b|\bdashboard\b|\bplugin\b|"
    r"\bapi\b|\bsaas\b|\bsubscription\b|\bworkflow\b|\bintegration\b",
    re.IGNORECASE | re.UNICODE)

MARKETING = re.compile(
    r"\bwe (?:solve|built|help you)\b|\bsign up (?:now|today)\b|\bour platform\b|\bbook a demo\b|"
    r"سجل الآن|منصتنا|نحن نحل", re.IGNORECASE | re.UNICODE)

# "بدون تعقيد" / "without hassle" is a sales promise, not a complaint. A pain
# word immediately preceded by a negator inverts the meaning, so the match is
# discarded rather than scored.
NEGATED_PAIN = re.compile(
    r"(?:بدون|بلا|من\s+غير|دون|ما\s+في|مافي|لا\s+يوجد\s+أي)\s+"
    r"(?:تعقيد\w*|مشاكل|مشكلة|صعوبة|عناء|تعب|خبرة|رأس\s*مال)|"
    r"\b(?:without|no|zero)\s+(?:hassle|problems?|complexity|headaches?|effort)\b",
    re.IGNORECASE | re.UNICODE)

_SENT_SPLIT = re.compile(r"(?<=[.!?؟。])\s+|\n+")
MIN_QUOTE_CHARS = 25


@dataclass
class Signal:
    quote: str
    pain_type: str
    clarity: float
    segment: Optional[str] = None
    severity_claim: Optional[str] = None
    money_time_impact: Optional[str] = None
    current_workaround: Optional[str] = None
    wtp_signal: Optional[str] = None
    evidence_limits: str = ""
    extractor: str = "rules:v1"
    matched: list[str] = field(default_factory=list)


def _sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENT_SPLIT.split(text or "") if p and p.strip()]
    out: list[str] = []
    for p in parts:
        # keep very long sentences manageable
        if len(p) > 600:
            out.extend(p[i:i + 600] for i in range(0, len(p), 600))
        else:
            out.append(p)
    return out


def _segment_of(text: str) -> Optional[str]:
    for name, rx in SEGMENTS.items():
        if rx.search(text):
            return name
    return None


def extract_from_text(text: str, domain_terms: Iterable[str] = (),
                      kind: str = "post", extraction_method: str = "read_full",
                      apply_quality_gate: bool = True,
                      require_domain_term: bool = False,
                      exclude_terms: Iterable[str] = ()) -> list[Signal]:
    """Rule-based extraction. One signal per (sentence, pain_type).

    Content that the quality gate rejects (SEO/agency spam, bot-generated
    templates) yields NO signals: it is not user-reported pain and must never
    reach the report as market evidence.

    With require_domain_term=True a signal is only kept when the quote actually
    mentions a domain/sector term. This is essential on general-purpose sources
    (e.g. GitHub), where trigger words like "manual" fire constantly in
    unrelated engineering contexts and would otherwise flood the results.
    """
    if not text or len(text.strip()) < MIN_QUOTE_CHARS:
        return []
    # A video/post description is the publisher's own marketing copy. It is kept
    # as context and provenance, but it is never user-reported pain.
    if kind == "description":
        return []
    q = assess(text)
    if apply_quality_gate and q.verdict == REJECT:
        return []
    dterms = [normalize(normalize_arabic(t)) for t in domain_terms if t and len(t) > 2]
    xterms = [normalize(normalize_arabic(t)) for t in exclude_terms if t and len(t) > 2]
    sents = _sentences(text)
    out: list[Signal] = []
    # A homonym trap anywhere in the text disqualifies the whole item: a comment
    # about the Google Play store is not merchant pain, whatever else it says.
    if xterms:
        ntext = normalize(text)
        if any(xt in ntext for xt in xterms):
            return []

    for idx, sent in enumerate(sents):
        hits: dict[str, tuple[float, list[str]]] = {}
        if NEGATED_PAIN.search(sent):
            continue
        for ptype, weight, rx in PATTERNS:
            m = rx.search(sent)
            if m:
                w, got = hits.get(ptype, (0.0, []))
                hits[ptype] = (max(w, weight), got + [m.group(0)[:60]])
        if not hits:
            continue

        # widen the quote to neighbours for readable context
        lo = max(0, idx - 1)
        hi = min(len(sents), idx + 2)
        quote = snippet(" ".join(sents[lo:hi]), 500)
        if len(quote) < MIN_QUOTE_CHARS:
            continue

        nquote = normalize(quote)
        nsent = normalize(sent)
        has_ctx = bool(CONTEXT_HINT.search(quote))
        # Domain relevance is measured on the *matched sentence*, not the widened
        # quote: a trigger word three sentences away from a domain term is not
        # evidence about that domain.
        has_domain = any(dt and dt in nsent for dt in dterms)
        has_domain_nearby = any(dt and dt in nquote for dt in dterms)
        is_question = bool(re.search(r"[?؟]\s*$", sent.strip()))
        is_marketing = bool(MARKETING.search(quote))

        impact_m = IMPACT.search(quote)
        wtp_m = WTP.search(quote)
        workaround = None
        if "manual_workaround" in hits:
            workaround = hits["manual_workaround"][1][0]
        elif re.search(r"\bexcel\b|\bspreadsheet\b|اكسل|جدول", quote, re.IGNORECASE):
            workaround = "spreadsheet mentioned"

        if require_domain_term and not has_domain:
            continue

        for ptype, (weight, matched) in hits.items():
            # Calibrated to spread across 0.2-0.95 so clarity is usable for
            # ranking instead of saturating at 1.0 on any explicit complaint.
            clarity = 0.20 + 0.25 * weight
            if has_domain:
                clarity += 0.15
            elif has_domain_nearby:
                clarity += 0.05
            if has_ctx:
                clarity += 0.08
            if impact_m:
                clarity += 0.15
            if wtp_m:
                clarity += 0.07
            if len(quote) > 120:
                clarity += 0.05
            if is_question and ptype in ("help_request", "missing_tool"):
                clarity -= 0.05
            if is_marketing:
                clarity -= 0.25
            if extraction_method == "metadata_only":
                clarity -= 0.15
            if q.verdict == WEAK:
                clarity -= 0.20
            if q.first_person:
                clarity += 0.07
            clarity = round(max(0.05, min(1.0, clarity)), 3)

            limits: list[str] = []
            if not has_domain:
                limits.append("no domain term in the sentence that triggered this signal; "
                              "relevance to the target market is unconfirmed")
            if extraction_method == "metadata_only":
                limits.append("derived from metadata/description, not from the full content body")
            elif extraction_method == "user_supplied":
                limits.append("user-supplied import; original context not independently re-fetched")
            if is_marketing:
                limits.append("quote resembles promotional copy, not a user complaint")
            if is_question:
                limits.append("phrased as a question; the problem may be informational, not a felt pain")
            if not impact_m:
                limits.append("no quantified time/money impact stated")
            if not wtp_m:
                limits.append("no willingness-to-pay language present")
            if q.verdict == WEAK:
                limits.append("content-quality gate: " + "; ".join(q.reasons))
            if not q.first_person:
                limits.append("no first-person voice; the author may be describing the problem "
                              "generally rather than experiencing it")
            limits.append("single author; one post is not evidence of market-wide demand")

            out.append(Signal(
                quote=quote, pain_type=ptype, clarity=clarity,
                segment=_segment_of(quote),
                severity_claim=matched[0] if matched else None,
                money_time_impact=impact_m.group(0) if impact_m else None,
                current_workaround=workaround,
                wtp_signal=wtp_m.group(0) if wtp_m else None,
                evidence_limits="; ".join(limits),
                extractor="rules:v1", matched=matched,
            ))
    return out


def signal_hash(content_id: str, quote: str, pain_type: str) -> str:
    return short_hash(f"{content_id}|{pain_type}|{normalize(quote)}", 32)


def persist_signals(conn, project_id: str, content_id: str, signals: list[Signal],
                    data_origin: str = db.REAL, min_clarity: float = 0.0) -> list[str]:
    ids: list[str] = []
    for s in signals:
        if s.clarity < min_clarity:
            continue
        h = signal_hash(content_id, s.quote, s.pain_type)
        sid = db.new_id("sig")
        cur = conn.execute(
            "INSERT INTO pain_signals(id,project_id,content_id,quote,pain_type,segment,clarity,"
            "severity_claim,money_time_impact,current_workaround,wtp_signal,evidence_limits,"
            "verification_status,extractor,signal_hash,created_at,data_origin)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,'unverified',?,?,?,?)"
            " ON CONFLICT(project_id,signal_hash) DO NOTHING",
            (sid, project_id, content_id, s.quote, s.pain_type, s.segment, s.clarity,
             s.severity_claim, s.money_time_impact, s.current_workaround, s.wtp_signal,
             s.evidence_limits, s.extractor, h, db.now(), data_origin),
        )
        if cur.rowcount:
            ids.append(sid)
    conn.commit()
    return ids


def run_extraction(conn, project_id: str, domain_terms: Iterable[str] = (),
                   data_origin: str = db.REAL, min_clarity: float = 0.0,
                   run_id: Optional[str] = None,
                   require_domain_term: bool = True,
                   exclude_terms: Iterable[str] = ()) -> dict:
    """Extract from every not-yet-processed content row of this origin."""
    from .store import contents_for
    rows_ = contents_for(conn, project_id, data_origin=data_origin)
    stats = {"contents_scanned": 0, "signals_created": 0, "contents_with_signals": 0,
             "rejected_low_quality": 0, "reject_reasons": {},
             "require_domain_term": require_domain_term, "min_clarity": min_clarity,
             "domain_terms": list(domain_terms)[:12],
             "excluded_off_domain": 0}
    for r in rows_:
        already = db.one(conn, "SELECT COUNT(*) FROM pain_signals WHERE content_id=?", (r["id"],))
        if already and already[0]:
            continue
        stats["contents_scanned"] += 1
        q = assess(r["text"])
        if q.verdict == REJECT:
            stats["rejected_low_quality"] += 1
            key = (q.reasons or ["unspecified"])[0]
            stats["reject_reasons"][key] = stats["reject_reasons"].get(key, 0) + 1
            continue
        sigs = extract_from_text(r["text"], domain_terms=domain_terms,
                                 kind=r["kind"], extraction_method=r["extraction_method"],
                                 require_domain_term=require_domain_term,
                                 exclude_terms=exclude_terms)
        created = persist_signals(conn, project_id, r["id"], sigs,
                                  data_origin=data_origin, min_clarity=min_clarity)
        if created:
            stats["contents_with_signals"] += 1
            stats["signals_created"] += len(created)
    db.log(conn, "info", "extract", f"extraction done: {stats}", project_id=project_id,
           run_id=run_id, payload=stats)
    return stats
