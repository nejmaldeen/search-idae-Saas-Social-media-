"""Opportunity Evaluation Engine.

Produces a *heuristic, rule-declared* ranking - explicitly NOT a probability of
commercial success. Two scores are kept apart on purpose:

  evidence_strength : how much the collected sample actually supports the claim
                      that this problem exists and is felt. Derived only from
                      counted observations.
  attractiveness    : how appealing the opportunity looks as an AI SaaS bet.
                      Partly inference; labelled as such.

Every criterion carries: score, max, the rule applied, and the basis (the
counted observation). Nothing is weighted by an undeclared magic number.
"""
from __future__ import annotations

from typing import Optional

from . import db
from .cluster import cluster_evidence, list_clusters
from .competitors import ABSENCE_DISCLAIMER, list_competitors

SCALE = 3  # every criterion is 0..3

EVIDENCE_CRITERIA = ["frequency", "severity", "quantified_impact",
                     "alternatives_in_use", "wtp_signals"]
ATTRACTIVENESS_CRITERIA = ["audience_clarity", "competitive_gap", "ai_solvability",
                           "testability", "marketing_clarity"]

# AI-amenable problem shapes. Used for a declared, inspectable heuristic.
_AI_FRIENDLY = {
    "manual_workaround": "repetitive manual data handling - automatable",
    "time_drain": "recurring time sink - automatable",
    "reliability": "data reconciliation / error detection - ML-amenable",
    "missing_feature": "capability gap - may be a feature, not a product",
    "missing_tool": "no tool exists in the user's awareness - greenfield",
    "alternative_seeking": "active switching intent - distribution advantage",
    "cost": "price objection - cheaper automation may win",
    "help_request": "knowledge gap - may be solved by content, not software",
    "frustration": "sentiment only - problem shape unclear",
}
_AI_SCORE = {"manual_workaround": 3, "time_drain": 3, "reliability": 3,
             "missing_tool": 2, "missing_feature": 2, "alternative_seeking": 2,
             "cost": 1, "help_request": 1, "frustration": 0}


def _crit(score: int, rule: str, basis: str) -> dict:
    return {"score": int(max(0, min(SCALE, score))), "max": SCALE, "rule": rule, "basis": basis}


def score_cluster(conn, project_id: str, cluster_row, data_origin: str = db.REAL) -> dict:
    ev = cluster_evidence(conn, cluster_row["id"])
    n = len(ev)
    authors = {e["author_ref"] for e in ev if e["author_ref"]}
    platforms = {e["platform"] for e in ev if e["platform"]}
    impacts = [e["money_time_impact"] for e in ev if e["money_time_impact"]]
    wtps = [e["wtp_signal"] for e in ev if e["wtp_signal"]]
    workarounds = [e["current_workaround"] for e in ev if e["current_workaround"]]
    segments = {e["segment"] for e in ev if e["segment"]}
    types = {e["pain_type"] for e in ev if e["pain_type"]}
    max_clarity = max([e["clarity"] or 0 for e in ev], default=0.0)
    competitors = list_competitors(conn, project_id, data_origin=data_origin)

    rubric: dict[str, dict] = {}

    # ---------------- evidence strength (counted observations only) ----------
    rubric["frequency"] = _crit(
        3 if len(authors) >= 5 else 2 if len(authors) >= 3 else 1 if len(authors) >= 2 else 0,
        "distinct authors in sample: >=5 ->3, >=3 ->2, >=2 ->1, else 0",
        f"{n} signal(s) from {len(authors)} distinct author(s) across {len(platforms)} platform(s)")
    rubric["severity"] = _crit(
        3 if max_clarity >= 0.8 else 2 if max_clarity >= 0.6 else 1 if max_clarity >= 0.4 else 0,
        "highest signal clarity in cluster: >=0.8 ->3, >=0.6 ->2, >=0.4 ->1, else 0",
        f"max clarity {max_clarity:.2f}; pain types observed: {', '.join(sorted(types)) or 'none'}")
    rubric["quantified_impact"] = _crit(
        3 if len(impacts) >= 3 else 2 if len(impacts) == 2 else 1 if impacts else 0,
        "quotes containing a number + time/money unit: >=3 ->3, 2 ->2, 1 ->1, 0 ->0",
        f"{len(impacts)} quantified mention(s): {'; '.join(impacts[:4]) or 'none'}")
    rubric["alternatives_in_use"] = _crit(
        3 if len(workarounds) >= 3 else 2 if len(workarounds) == 2 else 1 if workarounds else 0,
        "quotes showing a current workaround or named tool: >=3 ->3, 2 ->2, 1 ->1, 0 ->0",
        f"{len(workarounds)} workaround mention(s); {len(competitors)} named tool(s) in project")
    rubric["wtp_signals"] = _crit(
        3 if len(wtps) >= 2 else 2 if wtps else 0,
        "explicit willingness-to-pay language: >=2 ->3, 1 ->2, 0 ->0 "
        "(language only; no payment has been observed)",
        f"{len(wtps)} WTP phrase(s): {'; '.join(w[:40] for w in wtps[:3]) or 'none'}")

    # ---------------- attractiveness (judgment, partly inference) -----------
    rubric["audience_clarity"] = _crit(
        3 if len(segments) == 1 else 2 if len(segments) == 2 else 1 if segments else 0,
        "distinct segments named in evidence: exactly 1 ->3, 2 ->2, >=3 ->1, none ->0",
        f"segments in evidence: {', '.join(sorted(segments)) or 'none stated'}")
    dom = max(types, key=lambda t: _AI_SCORE.get(t, 0)) if types else None
    rubric["competitive_gap"] = _crit(
        2 if competitors else 1,
        "named competitors present ->2 (gap assessable from complaints); "
        "none named ->1 (gap UNKNOWN, not zero)",
        f"{len(competitors)} competitor(s) named in evidence. {ABSENCE_DISCLAIMER}")
    rubric["ai_solvability"] = _crit(
        _AI_SCORE.get(dom, 0) if dom else 0,
        "declared mapping from dominant pain type to AI-amenability (see _AI_SCORE)",
        f"dominant type '{dom}': {_AI_FRIENDLY.get(dom, 'unmapped')}" if dom else "no pain type")
    rubric["testability"] = _crit(
        3 if (segments and len(authors) >= 2) else 2 if segments or len(authors) >= 2 else 1,
        "named segment AND >=2 reachable authors ->3; one of the two ->2; neither ->1",
        f"{len(authors)} identifiable public author(s); segment {'named' if segments else 'not named'}")
    rubric["marketing_clarity"] = _crit(
        3 if impacts and segments else 2 if impacts or segments else 1,
        "quantified impact AND named segment ->3; one ->2; neither ->1",
        "a concrete number plus a named audience makes the value claim statable")

    ev_raw = sum(rubric[k]["score"] for k in EVIDENCE_CRITERIA)
    at_raw = sum(rubric[k]["score"] for k in ATTRACTIVENESS_CRITERIA)
    ev_max = SCALE * len(EVIDENCE_CRITERIA)
    at_max = SCALE * len(ATTRACTIVENESS_CRITERIA)

    facts, inferences, assumptions = [], [], []
    facts.append(f"{n} de-duplicated pain signal(s) from {len(authors)} distinct public author(s) "
                 f"on {len(platforms)} platform(s) matched this problem concept in the collected sample.")
    if impacts:
        facts.append(f"Quantified impact stated verbatim in evidence: {'; '.join(impacts[:4])}.")
    if workarounds:
        facts.append(f"Current workaround(s) stated in evidence: {'; '.join(sorted(set(workarounds))[:4])}.")
    if wtps:
        facts.append(f"Willingness-to-pay language present (language only, no transaction observed): "
                     f"{'; '.join(w[:60] for w in wtps[:3])}.")
    if competitors:
        facts.append(f"Tools named in evidence: {', '.join(c['name'] for c in competitors[:8])}.")

    if dom:
        inferences.append(f"The dominant framing is '{dom}', which the declared heuristic maps to: "
                          f"{_AI_FRIENDLY.get(dom, 'unmapped')}. This is the model's reading, not a finding.")
    inferences.append("Grouping of these signals into one problem concept is an algorithmic similarity "
                      "judgment and may merge distinct root causes.")
    if not wtps:
        inferences.append("No pricing signal was observed, so any revenue framing below is inference only.")

    assumptions.append("That the collected sample is representative of the target market - UNVERIFIED; "
                       "the sample is biased toward the platforms and queries actually executed.")
    assumptions.append(f"That the {len(authors)} author(s) seen are distinct real people in the target "
                       "segment - not verified against any identity or firmographic check.")
    assumptions.append("That stated frustration converts into budget - not established by any evidence here.")
    if cluster_row["knowledge_gaps"]:
        assumptions.append("Open knowledge gaps recorded on the cluster: " + cluster_row["knowledge_gaps"])

    experiments = _experiments(rubric, segments, authors, impacts, wtps, competitors)

    return {
        "rubric": rubric,
        "evidence_strength": round(ev_raw / ev_max, 3),
        "attractiveness": round(at_raw / at_max, 3),
        "evidence_raw": f"{ev_raw}/{ev_max}",
        "attractiveness_raw": f"{at_raw}/{at_max}",
        "facts": facts, "inferences": inferences, "assumptions": assumptions,
        "experiments": experiments,
        "dominant_type": dom,
        "distinct_authors": len(authors),
        "distinct_platforms": len(platforms),
    }


def _experiments(rubric: dict, segments: set, authors: set, impacts: list,
                 wtps: list, competitors: list) -> list[str]:
    out: list[str] = []
    if rubric["frequency"]["score"] <= 1:
        out.append("Widen collection: run the unexecuted queries on at least one more platform "
                   "and re-cluster. Target: >=5 distinct authors before treating this as a pattern.")
    if not impacts:
        out.append("Quantify the cost: interview 5 people from the segment and ask for minutes/week "
                   "and money spent on the current workaround. Target: a median number.")
    if not wtps:
        out.append("Price probe: present the problem statement and 3 price points to 10 prospects; "
                   "record stated intent AND a reversible commitment (pre-order, deposit, pilot slot).")
    if not segments:
        out.append("Define the buyer: classify 20 evidence authors by role/company size from their "
                   "public profiles before building anything.")
    if not competitors:
        out.append("Disconfirming competitor search: check vendor directories and app marketplaces "
                   "directly. Do not treat the current empty result as 'no competition'.")
    else:
        out.append(f"Review low-star reviews of {', '.join(c['name'] for c in competitors[:3])} "
                   "to test whether the gap is real or already solved.")
    out.append("Falsification test: deliberately search for evidence that this problem is already "
               "solved or not felt, and record what is found.")
    out.append("Smoke test: a landing page stating the problem in the users' own words, measuring "
               "qualified sign-ups from the named segment (not raw traffic).")
    return out


def build_opportunities(conn, project_id: str, data_origin: str = db.REAL,
                        min_signals: int = 1, run_id: Optional[str] = None) -> dict:
    """Score every cluster into an opportunity hypothesis. Idempotent per origin."""
    conn.execute("DELETE FROM opportunities WHERE project_id=? AND data_origin=?",
                 (project_id, data_origin))
    conn.commit()
    clusters = list_clusters(conn, project_id, data_origin=data_origin)
    made = 0
    for cl in clusters:
        if (cl["distinct_sources"] or 0) < min_signals:
            continue
        sc = score_cluster(conn, project_id, cl, data_origin=data_origin)
        title = f"AI SaaS hypothesis: {cl['label']}"
        hypothesis = (
            f"IF {sc['distinct_authors']} or more {', '.join(sorted({x for x in [cl['audience']] if x})) or 'unspecified'} "
            f"users genuinely lose time/money to \"{(cl['problem_statement'] or '')[:160]}\", "
            f"THEN an AI SaaS that automates it should produce measurable adoption. "
            f"This is an UNTESTED hypothesis derived from {sc['distinct_authors']} public author(s) "
            f"on {sc['distinct_platforms']} platform(s)."
        )
        conn.execute(
            "INSERT INTO opportunities(id,project_id,cluster_id,title,hypothesis,assumptions,facts,"
            "inferences,evidence_strength,attractiveness,rubric_json,next_experiments,created_at,data_origin)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (db.new_id("opp"), project_id, cl["id"], title, hypothesis,
             db.jdump(sc["assumptions"]), db.jdump(sc["facts"]), db.jdump(sc["inferences"]),
             sc["evidence_strength"], sc["attractiveness"],
             db.jdump({"criteria": sc["rubric"], "evidence_raw": sc["evidence_raw"],
                       "attractiveness_raw": sc["attractiveness_raw"], "scale": SCALE,
                       "disclaimer": "Heuristic rule-based ranking. NOT a probability of success."}),
             db.jdump(sc["experiments"]), db.now(), data_origin))
        made += 1
    conn.commit()
    stats = {"opportunities": made, "clusters_considered": len(clusters)}
    db.log(conn, "info", "evaluate", f"opportunities built: {stats}", project_id=project_id,
           run_id=run_id, payload=stats)
    return stats


def list_opportunities(conn, project_id: str, data_origin: str = db.REAL) -> list:
    return db.rows(conn,
        "SELECT o.*, c.label AS cluster_label, c.distinct_authors, c.distinct_sources,"
        " c.knowledge_gaps, c.audience"
        " FROM opportunities o LEFT JOIN clusters c ON c.id=o.cluster_id"
        " WHERE o.project_id=? AND o.data_origin=?"
        " ORDER BY o.evidence_strength DESC, o.attractiveness DESC", (project_id, data_origin))
