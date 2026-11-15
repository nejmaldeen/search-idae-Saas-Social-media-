from oda.textutil import (content_hash, detect_lang, jaccard, normalize,
                          normalize_arabic, shingles, token_overlap)


def test_detect_lang():
    assert detect_lang("hello world this is english") == "en"
    assert detect_lang("مرحبا هذا نص عربي كامل") == "ar"
    assert detect_lang("inventory مخزون mixed نص text here") == "mixed"
    assert detect_lang("") == "unknown"


def test_arabic_normalization_unifies_variants():
    # alef variants, ta marbuta and diacritics must collapse
    assert normalize_arabic("إدارة") == normalize_arabic("ادارة")
    assert normalize_arabic("مشكلة") == normalize_arabic("مشكله")
    assert normalize("المَخْزُون") == normalize("المخزون")


def test_content_hash_stable_under_punctuation_and_case():
    assert content_hash("Inventory problems!!") == content_hash("inventory problems")
    assert content_hash("a") != content_hash("b")


def test_similarity_bounds():
    a, b = shingles("inventory sync is broken between store and sheet"), shingles(
        "inventory sync is broken between store and sheet")
    assert jaccard(a, b) == 1.0
    assert jaccard(a, shingles("completely different topic entirely")) < 0.2
    assert token_overlap("", "x") == 0.0
