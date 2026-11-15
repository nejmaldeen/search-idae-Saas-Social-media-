"""Competitor Intelligence Engine.

Extracts named tools/products mentioned in collected evidence. Two hard rules:
  * a competitor row always points at the evidence that mentioned it;
  * absence of a competitor from search results is NEVER recorded as proof
    that no competitor exists (see `absence_disclaimer`).

Pricing is only stored when it appears verbatim in evidence, with its source
URL. The engine does not guess prices.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Iterable, Optional

from . import db
from .dedupe import unique_signals

ABSENCE_DISCLAIMER = (
    "No competitor found in the collected sample is NOT evidence that none exists. "
    "This sample covers only the platforms and queries listed in this project, over "
    "the period collected. A dedicated competitor search (vendor directories, app "
    "stores, marketplace listings) is required before any 'no competition' claim."
)

# Explicit "named alternative" captures, both languages.
_ALT_PATTERNS = [
    re.compile(r"alternatives?\s+to\s+([A-Z][\w.\-]{2,24}(?:\s+[A-Z][\w.\-]{2,24})?)", re.UNICODE),
    re.compile(r"(?:switch(?:ing|ed)?|migrat(?:e|ing|ed))\s+(?:away\s+)?from\s+([A-Z][\w.\-]{2,24})", re.UNICODE),
    re.compile(r"(?:we|i)\s+(?:use|used|tried)\s+([A-Z][\w.\-]{2,24})\b", re.UNICODE),
    re.compile(r"بديل\s+([A-Za-z][\w.\-]{2,24})", re.UNICODE),
    re.compile(r"(?:أستخدم|استخدم|نستخدم|جربت)\s+([A-Za-z][\w.\-]{2,24})", re.UNICODE),
]

# Verbatim price mentions near a tool name.
_PRICE = re.compile(
    r"((?:\$|usd|sar|aed|ريال|درهم)\s?\d+(?:[.,]\d+)?|\d+(?:[.,]\d+)?\s?(?:\$|usd|sar|aed|ريال|درهم))"
    r"\s*(?:/|per\s+|في\s+ال|شهري)?\s*(mo|month|year|شهر|سنة)?",
    re.IGNORECASE | re.UNICODE)

# Words that look capitalized but are not products.
_STOPNAMES = {
    "I", "We", "The", "This", "That", "It", "My", "Our", "You", "They", "He", "She",
    "And", "But", "For", "With", "From", "Also", "However", "When", "What", "Why",
    "How", "If", "So", "There", "Here", "Now", "Then", "All", "Any", "One", "Two",
    "Google", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
    "Sunday", "January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December", "API", "SaaS", "AI",
    "CSV", "PDF", "URL", "HTTP", "JSON", "OK", "US", "UK", "UAE", "KSA",
    "Win7", "Win8", "Win10", "Win11", "Windows", "Linux", "Ubuntu", "macOS",
    "Chrome", "Firefox", "Safari", "Edge", "Android", "iOS", "Excel", "Word",
    "Rust", "Zig", "Python", "Java", "Node", "React", "Docker", "GitHub",
}


def extract_candidates(text: str, known: Iterable[str] = ()) -> Counter:
    """Return Counter of candidate product names found in `text`."""
    found: Counter = Counter()
    for kn in known:
        if kn and re.search(rf"\b{re.escape(kn)}\b", text, re.IGNORECASE):
            found[kn] += 1
    for rx in _ALT_PATTERNS:
        for m in rx.finditer(text):
            name = (m.group(1) or "").strip(" .,:;!?")
            if not name or name in _STOPNAMES or len(name) < 4:
                continue
            # reject fragments of a known non-product word (e.g. "Goog" <- Google)
            low = name.lower()
            if any(sn.lower().startswith(low) and sn.lower() != low for sn in _STOPNAMES):
                continue
            if name.lower() in {k.lower() for k in found}:
                continue
            found[name] += 1
    return found


def find_price(text: str) -> Optional[str]:
    m = _PRICE.search(text or "")
    return m.group(0).strip() if m else None


def run_competitor_scan(conn, project_id: str, known_tools: Iterable[str] = (),
                        data_origin: str = db.REAL,
                        run_id: Optional[str] = None) -> dict:
    """Scan unique pain-signal evidence for competitor mentions."""
    sigs = unique_signals(conn, project_id, data_origin=data_origin)
    agg: dict[str, dict] = {}
    for s in sigs:
        cands = extract_candidates(s["quote"], known=known_tools)
        for name, n in cands.items():
            key = name.lower()
            rec = agg.setdefault(key, {
                "name": name, "count": 0, "complaints": [], "urls": [],
                "price": None, "price_url": None, "source_id": None,
            })
            rec["count"] += n
            if s["pain_type"] in ("cost", "missing_feature", "reliability",
                                  "frustration", "alternative_seeking"):
                rec["complaints"].append(f"[{s['pain_type']}] {s['quote'][:180]}")
            if s["url"]:
                rec["urls"].append(s["url"])
            if rec["price"] is None:
                p = find_price(s["quote"])
                if p:
                    rec["price"], rec["price_url"] = p, s["url"]

    created = updated = 0
    for key, rec in agg.items():
        complaints = "\n".join(rec["complaints"][:8]) or "none captured in this sample"
        gaps = ("Derived only from user complaints in this sample; feature matrix NOT verified "
                "against the vendor's own documentation.")
        cid = db.new_id("cmp")
        cur = conn.execute(
            "INSERT INTO competitors(id,project_id,name,url,pricing_text,pricing_evidence_url,"
            "features,complaints,gaps,mention_count,created_at,data_origin)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(project_id,name) DO UPDATE SET"
            " mention_count=mention_count+excluded.mention_count,"
            " complaints=excluded.complaints,"
            " pricing_text=COALESCE(competitors.pricing_text, excluded.pricing_text),"
            " pricing_evidence_url=COALESCE(competitors.pricing_evidence_url, excluded.pricing_evidence_url)",
            (cid, project_id, rec["name"], (rec["urls"][0] if rec["urls"] else None),
             rec["price"], rec["price_url"], "not verified from vendor docs",
             complaints, gaps, rec["count"], db.now(), data_origin),
        )
        if cur.rowcount == 1:
            created += 1
        else:
            updated += 1
    conn.commit()
    stats = {"competitors_created": created, "competitors_updated": updated,
             "candidates": len(agg), "absence_disclaimer": ABSENCE_DISCLAIMER}
    db.log(conn, "info", "competitors", f"competitor scan: {created} new / {updated} updated",
           project_id=project_id, run_id=run_id, payload=stats)
    return stats


def add_competitor(conn, project_id: str, name: str, url: Optional[str] = None,
                   pricing_text: Optional[str] = None, pricing_evidence_url: Optional[str] = None,
                   features: Optional[str] = None, complaints: Optional[str] = None,
                   gaps: Optional[str] = None, data_origin: str = db.REAL) -> str:
    """Manually recorded competitor (from human review)."""
    cid = db.new_id("cmp")
    conn.execute(
        "INSERT INTO competitors(id,project_id,name,url,pricing_text,pricing_evidence_url,"
        "features,complaints,gaps,mention_count,created_at,data_origin)"
        " VALUES(?,?,?,?,?,?,?,?,?,0,?,?)"
        " ON CONFLICT(project_id,name) DO UPDATE SET"
        " url=COALESCE(excluded.url,competitors.url),"
        " pricing_text=COALESCE(excluded.pricing_text,competitors.pricing_text),"
        " pricing_evidence_url=COALESCE(excluded.pricing_evidence_url,competitors.pricing_evidence_url),"
        " features=COALESCE(excluded.features,competitors.features),"
        " complaints=COALESCE(excluded.complaints,competitors.complaints),"
        " gaps=COALESCE(excluded.gaps,competitors.gaps)",
        (cid, project_id, name, url, pricing_text, pricing_evidence_url,
         features, complaints, gaps or "manually entered; not independently verified",
         db.now(), data_origin))
    conn.commit()
    row = db.one(conn, "SELECT id FROM competitors WHERE project_id=? AND name=?", (project_id, name))
    return row["id"] if row else cid


def list_competitors(conn, project_id: str, data_origin: str = db.REAL) -> list:
    return db.rows(conn, "SELECT * FROM competitors WHERE project_id=? AND data_origin=?"
                         " ORDER BY mention_count DESC, name", (project_id, data_origin))
