from oda.extract import extract_from_text
from oda.quality import ACCEPT, REJECT, WEAK, assess

REAL_EN = ("I waste 4 hours every week manually reconciling stock between our Shopify store "
           "and the warehouse spreadsheet. There is no way to sync them automatically.")
REAL_AR = ("أنا صاحب متجر إلكتروني، أضيع 6 ساعات أسبوعياً في مطابقة المخزون يدوياً بين سلة "
           "وملف الإكسل. أتمنى لو توجد أداة تربطهم. مستعد أدفع 200 ريال شهرياً.")


def test_quality_rejects_seo_spam():
    q = assess("Modern logistics software can bring together transportation management, "
               "warehouse operations and inventory control for growing businesses.")
    assert q.verdict == REJECT
    assert any("promotional" in r for r in q.reasons)


def test_quality_rejects_agency_geo_spam():
    q = assess("Cloud services Businesses modernizing legacy systems also benefit from CMS "
               "migration services in Coimbatore with our expert team.")
    assert q.verdict == REJECT


def test_quality_rejects_bot_template():
    q = assess("### DASHBOARD-CARD-CADENCE-20261111 authorized implementation WIP owner requests")
    assert q.verdict == REJECT
    assert any("bot/template" in r for r in q.reasons)


def test_quality_accepts_first_person_pain():
    assert assess(REAL_EN).verdict == ACCEPT
    assert assess(REAL_AR).verdict == ACCEPT


def test_quality_marks_third_person_description_weak():
    q = assess("Inventory management is an important part of running an online store "
               "and many different tools exist for it today.")
    assert q.verdict == WEAK
    assert q.first_person is False


def test_spam_yields_no_signals():
    assert extract_from_text("We offer the best inventory services in Dubai. Contact us today "
                             "for a free consultation and boost your sales.") == []


def test_extracts_english_pain_with_impact():
    sigs = extract_from_text(REAL_EN, domain_terms=["stock", "inventory", "store"])
    types = {s.pain_type for s in sigs}
    assert "manual_workaround" in types or "time_drain" in types
    assert any(s.money_time_impact for s in sigs)


def test_extracts_arabic_pain_with_wtp_and_segment():
    sigs = extract_from_text(REAL_AR, domain_terms=["مخزون", "متجر"])
    assert sigs, "Arabic extraction must produce signals"
    assert any(s.wtp_signal for s in sigs), "willingness-to-pay language must be captured"
    assert any(s.segment == "store_owner" for s in sigs)


def test_irrelevant_text_yields_nothing():
    assert extract_from_text("The weather is lovely today and I had a nice walk in the park.") == []


def test_every_signal_carries_evidence_limits():
    for s in extract_from_text(REAL_EN, domain_terms=["inventory"]):
        assert s.evidence_limits.strip(), "a signal without stated limits is not acceptable"
        assert "single author" in s.evidence_limits


def test_wtp_absence_is_recorded_as_a_limit():
    sigs = extract_from_text(REAL_EN, domain_terms=["inventory", "stock"])
    assert any("no willingness-to-pay" in s.evidence_limits for s in sigs)


def test_require_domain_term_filters_offtopic_matches():
    text = "I do this step manually every single time and it is a huge pain for our team."
    assert extract_from_text(text, domain_terms=["inventory"], require_domain_term=True) == []
    assert extract_from_text(text, domain_terms=["inventory"], require_domain_term=False) != []


def test_metadata_only_extraction_lowers_clarity():
    full = extract_from_text(REAL_EN, domain_terms=["inventory"], extraction_method="read_full")
    meta = extract_from_text(REAL_EN, domain_terms=["inventory"], extraction_method="metadata_only")
    assert max(s.clarity for s in meta) < max(s.clarity for s in full)
    assert any("metadata" in s.evidence_limits for s in meta)
