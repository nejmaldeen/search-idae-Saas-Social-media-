"""De-duplication.

Three distinct things are separated, because conflating them inflates results:
  1. identical content re-posted (same normalized text)  -> exact duplicate
  2. near-identical text (reposts, quote-tweets, boilerplate) -> near duplicate
  3. different people describing the same problem -> NOT a duplicate; that is
     corroboration and is handled by clustering instead.

Post count is never converted into a user count: `distinct_authors` is tracked
separately and reported alongside.
"""
from __future__ import annotations

from typing import Optional

from . import db
from .textutil import jaccard, shingles

NEAR_DUP_THRESHOLD = 0.82
# For the SAME author, containment is the right test: one quote fully inside
# another is a repost/extension of one complaint, not a second data point.
SAME_AUTHOR_CONTAINMENT = 0.85
# Across DIFFERENT authors only near-verbatim text counts as a duplicate;
# anything less is treated as corroboration and left for clustering.
CROSS_AUTHOR_VERBATIM = 0.95


def mark_exact_duplicates(conn, project_id: str, data_origin: str = db.REAL) -> int:
    """Contents are already unique by content_hash; this catches signals whose
    normalized quote+type collide across different content rows (reposts)."""
    rows = db.rows(conn,
        "SELECT ps.id, ps.pain_type, ps.quote, ps.created_at, s.author_ref, c.content_hash"
        " FROM pain_signals ps"
        " JOIN contents c ON c.id=ps.content_id"
        " JOIN sources s ON s.id=c.source_id"
        " WHERE ps.project_id=? AND ps.data_origin=? AND ps.duplicate_of IS NULL"
        " ORDER BY ps.created_at", (project_id, data_origin))
    from .textutil import normalize
    seen: dict[tuple[str, str], str] = {}
    marked = 0
    for r in rows:
        key = (r["pain_type"], normalize(r["quote"]))
        if key in seen:
            conn.execute("UPDATE pain_signals SET duplicate_of=? WHERE id=?", (seen[key], r["id"]))
            marked += 1
        else:
            seen[key] = r["id"]
    conn.commit()
    return marked


def mark_near_duplicates(conn, project_id: str, data_origin: str = db.REAL,
                         threshold: float = NEAR_DUP_THRESHOLD) -> int:
    """Flag near-identical quotes.

    Same author  -> containment test (a repost or an extended version of one
                    complaint is still one complaint).
    Different authors -> only near-verbatim text is a duplicate; otherwise two
                    people describing the same problem is corroboration and is
                    handled by clustering, never collapsed away.
    """
    rows = db.rows(conn,
        "SELECT ps.id, ps.pain_type, ps.quote, s.author_ref, s.platform"
        " FROM pain_signals ps"
        " JOIN contents c ON c.id=ps.content_id"
        " JOIN sources s ON s.id=c.source_id"
        " WHERE ps.project_id=? AND ps.data_origin=? AND ps.duplicate_of IS NULL"
        " ORDER BY ps.created_at", (project_id, data_origin))
    sig = [(r["id"], r["pain_type"], r["author_ref"], shingles(r["quote"])) for r in rows]
    marked = 0
    kept: list[tuple[str, str, Optional[str], set]] = []
    for sid, ptype, author, sh in sig:
        dup_of = None
        for ksid, kptype, kauthor, ksh in kept:
            if kptype != ptype:
                continue
            score = jaccard(sh, ksh)
            containment = (len(sh & ksh) / min(len(sh), len(ksh))) if sh and ksh else 0.0
            same_author = bool(author and kauthor and author == kauthor)
            unknown_author = not author and not kauthor
            if same_author or unknown_author:
                is_dup = score >= threshold or containment >= SAME_AUTHOR_CONTAINMENT
            else:
                is_dup = score >= CROSS_AUTHOR_VERBATIM
            if is_dup:
                dup_of = ksid
                break
        if dup_of:
            conn.execute("UPDATE pain_signals SET duplicate_of=? WHERE id=?", (dup_of, sid))
            marked += 1
        else:
            kept.append((sid, ptype, author, sh))
    conn.commit()
    return marked


def run_dedupe(conn, project_id: str, data_origin: str = db.REAL,
               run_id: Optional[str] = None) -> dict:
    exact = mark_exact_duplicates(conn, project_id, data_origin)
    near = mark_near_duplicates(conn, project_id, data_origin)
    stats = {"exact_duplicates": exact, "near_duplicates": near}
    db.log(conn, "info", "dedupe", f"dedupe: {stats}", project_id=project_id,
           run_id=run_id, payload=stats)
    return stats


def unique_signals(conn, project_id: str, data_origin: str = db.REAL) -> list:
    return db.rows(conn,
        "SELECT ps.*, s.platform, s.url, s.author_ref, s.published_at, s.title AS src_title"
        " FROM pain_signals ps"
        " JOIN contents c ON c.id=ps.content_id"
        " JOIN sources s ON s.id=c.source_id"
        " WHERE ps.project_id=? AND ps.data_origin=? AND ps.duplicate_of IS NULL"
        " ORDER BY ps.clarity DESC", (project_id, data_origin))
