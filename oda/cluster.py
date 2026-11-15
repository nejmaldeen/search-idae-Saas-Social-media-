"""Problem clustering: group pain signals into problem concepts.

Single-link agglomeration on a containment-biased token similarity, restricted
to compatible pain types. Deterministic and dependency-free so results are
reproducible and reviewable.
"""
from __future__ import annotations

import math
from collections import Counter
from typing import Optional

from . import db
from .dedupe import unique_signals
from .textutil import jaccard, shingles, token_overlap, tokens

SIM_THRESHOLD = 0.34
# Cross-document merging uses a lower text bar when the two signals also share
# a salient (mid-IDF) concept token, so "inventory sync" complaints group even
# when the sentences are worded differently.
CONCEPT_SIM_THRESHOLD = 0.15
CONCEPT_TOKENS_PER_SIGNAL = 5

# pain types that may share a cluster (same underlying problem, different framing)
COMPATIBLE = [
    {"time_drain", "manual_workaround", "reliability"},
    {"missing_feature", "missing_tool", "alternative_seeking"},
    {"cost", "alternative_seeking"},
    {"frustration", "reliability", "time_drain"},
    {"help_request", "missing_tool"},
]

LABELS = {
    "time_drain": "Time lost to a repetitive task",
    "manual_workaround": "Manual / spreadsheet workaround in use",
    "missing_feature": "Missing capability in an existing tool",
    "missing_tool": "No suitable tool found",
    "cost": "Price/affordability objection",
    "alternative_seeking": "Actively shopping for a replacement",
    "frustration": "Expressed frustration with current state",
    "help_request": "Unanswered how-to / advice request",
    "reliability": "Data accuracy or reliability failure",
}


# tokens too generic to identify a problem concept
_GENERIC = {
    "the","and","for","with","from","that","this","have","has","not","but","you","your",
    "our","are","was","were","can","cant","could","would","should","will","just","like",
    "get","got","use","using","used","its","it s","they","them","there","what","when",
    "how","why","any","all","one","two","now","out","about","into","than","then","also",
    "some","more","most","very","really","still","even","only","other","same","need",
    "needs","want","wants","make","makes","take","takes","time","work","works","issue",
    "issues","problem","problems","way","ways","thing","things","please","thanks","hi",
    "في","من","على","الى","إلى","عن","مع","هذا","هذه","ذلك","التي","الذي","كل","بعض",
    "ما","لا","لم","لن","هل","او","أو","ثم","قد","كان","يكون","اي","أي","انا","أنا",
    "نحن","هو","هي","لكن","حتى","عند","بعد","قبل","جدا","جداً","مشكلة","مشاكل","شي",
}


def _concept_tokens(quotes: list[str], top_n: int = CONCEPT_TOKENS_PER_SIGNAL) -> list[set[str]]:
    """Per-quote salient token sets, selected by mid-band IDF.

    A token present in almost every quote carries no concept information; a
    token appearing once cannot link two signals. The middle band does.
    """
    docs = [set(t for t in tokens(q) if len(t) > 2 and t not in _GENERIC) for q in quotes]
    n = len(docs) or 1
    dfreq: Counter = Counter()
    for d in docs:
        dfreq.update(d)
    out: list[set[str]] = []
    for d in docs:
        scored = []
        for t in d:
            df = dfreq[t]
            if df >= max(2, int(0.9 * n)):     # too common to be a concept
                continue
            idf = math.log((n + 1) / (df + 0.5))
            scored.append((idf * (1.0 + 0.1 * len(t)), t))
        scored.sort(reverse=True)
        out.append({t for _, t in scored[:top_n]})
    return out


def _compatible(a: str, b: str) -> bool:
    if a == b:
        return True
    return any(a in grp and b in grp for grp in COMPATIBLE)


def build_clusters(conn, project_id: str, data_origin: str = db.REAL,
                   threshold: float = SIM_THRESHOLD,
                   run_id: Optional[str] = None) -> dict:
    sigs = unique_signals(conn, project_id, data_origin=data_origin)
    if not sigs:
        return {"clusters": 0, "members": 0, "signals": 0}

    # wipe previous clustering for this origin so re-runs are idempotent
    old = db.rows(conn, "SELECT id FROM clusters WHERE project_id=? AND data_origin=?",
                  (project_id, data_origin))
    for o in old:
        conn.execute("DELETE FROM cluster_members WHERE cluster_id=?", (o["id"],))
    conn.execute("DELETE FROM clusters WHERE project_id=? AND data_origin=?",
                 (project_id, data_origin))
    conn.commit()

    concepts = _concept_tokens([s["quote"] for s in sigs])
    prepared = [{
        "id": s["id"], "quote": s["quote"], "type": s["pain_type"],
        "content_id": s["content_id"], "concepts": concepts[i],
        "sh": shingles(s["quote"]), "author": s["author_ref"], "platform": s["platform"],
        "segment": s["segment"], "impact": s["money_time_impact"],
        "workaround": s["current_workaround"], "wtp": s["wtp_signal"],
        "clarity": s["clarity"], "url": s["url"], "limits": s["evidence_limits"],
    } for i, s in enumerate(sigs)]

    # single-link agglomeration via union-find
    parent = {p["id"]: p["id"] for p in prepared}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    sims: dict[tuple[str, str], float] = {}
    for i in range(len(prepared)):
        for j in range(i + 1, len(prepared)):
            a, b = prepared[i], prepared[j]
            if not _compatible(a["type"], b["type"]):
                continue
            score = max(token_overlap(a["quote"], b["quote"]), jaccard(a["sh"], b["sh"]))
            shared_concept = bool(a["concepts"] & b["concepts"])
            same_doc_same_type = (a["content_id"] == b["content_id"]
                                  and a["type"] == b["type"])
            merge = (
                # one complaint spread over adjacent sentences of one document
                same_doc_same_type
                # strong textual similarity on its own
                or score >= threshold
                # weaker text similarity, but the same named concept
                or (shared_concept and score >= CONCEPT_SIM_THRESHOLD)
            )
            if merge:
                sims[(a["id"], b["id"])] = max(score, 1.0 if same_doc_same_type else score)
                union(a["id"], b["id"])

    groups: dict[str, list[dict]] = {}
    for p in prepared:
        groups.setdefault(find(p["id"]), []).append(p)

    members = 0
    for root, grp in groups.items():
        types = Counter(g["type"] for g in grp)
        dom_type = types.most_common(1)[0][0]
        segs = Counter(g["segment"] for g in grp if g["segment"])
        authors = {g["author"] for g in grp if g["author"]}
        platforms = sorted({g["platform"] for g in grp})
        impacts = [g["impact"] for g in grp if g["impact"]]
        workarounds = sorted({g["workaround"] for g in grp if g["workaround"]})
        wtps = [g["wtp"] for g in grp if g["wtp"]]
        best = max(grp, key=lambda g: g["clarity"])

        gaps: list[str] = []
        if not impacts:
            gaps.append("no quantified time/money impact anywhere in this cluster")
        if not wtps:
            gaps.append("no willingness-to-pay language observed")
        if len(authors) < 2:
            gaps.append(f"only {len(authors) or 'unknown'} distinct author(s) - cannot be called a market pattern")
        if len(platforms) < 2:
            gaps.append(f"evidence from a single platform ({platforms[0] if platforms else 'n/a'}); platform-specific bias not ruled out")
        if not segs:
            gaps.append("affected segment not stated in the evidence")

        label = LABELS.get(dom_type, dom_type)
        cid = db.new_id("cls")
        conn.execute(
            "INSERT INTO clusters(id,project_id,label,problem_statement,audience,existing_solutions,"
            "impacts,knowledge_gaps,contradicting,distinct_sources,distinct_authors,created_at,data_origin)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (cid, project_id, f"{label} ({len(grp)} signal(s))",
             best["quote"][:400],
             ", ".join(f"{k}={v}" for k, v in segs.most_common()) or "not stated in evidence",
             ", ".join(workarounds) or "none observed",
             "; ".join(impacts[:6]) or "none quantified",
             "; ".join(gaps),
             "not assessed - requires a deliberate disconfirming search",
             len(grp), len(authors), db.now(), data_origin),
        )
        for g in grp:
            sim = 1.0 if g["id"] == best["id"] else sims.get((best["id"], g["id"]),
                                                             sims.get((g["id"], best["id"]), threshold))
            conn.execute("INSERT OR IGNORE INTO cluster_members(cluster_id,signal_id,similarity)"
                         " VALUES(?,?,?)", (cid, g["id"], sim))
            members += 1
    conn.commit()
    stats = {"clusters": len(groups), "members": members, "signals": len(prepared)}
    db.log(conn, "info", "cluster", f"clustering: {stats}", project_id=project_id,
           run_id=run_id, payload=stats)
    return stats


def list_clusters(conn, project_id: str, data_origin: str = db.REAL) -> list:
    return db.rows(conn,
        "SELECT * FROM clusters WHERE project_id=? AND data_origin=?"
        " ORDER BY distinct_authors DESC, distinct_sources DESC", (project_id, data_origin))


def cluster_evidence(conn, cluster_id: str) -> list:
    return db.rows(conn,
        "SELECT ps.*, s.platform, s.url, s.author_ref, s.published_at, cm.similarity,"
        " q.text AS found_by_query, c.extraction_method"
        " FROM cluster_members cm"
        " JOIN pain_signals ps ON ps.id=cm.signal_id"
        " JOIN contents c ON c.id=ps.content_id"
        " JOIN sources s ON s.id=c.source_id"
        " LEFT JOIN search_queries q ON q.id=s.query_id"
        " WHERE cm.cluster_id=? ORDER BY ps.clarity DESC", (cluster_id,))
