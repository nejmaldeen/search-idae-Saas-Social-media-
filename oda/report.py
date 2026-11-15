"""Report generation (Markdown + JSON).

The report must make three things impossible to confuse:
  * what the evidence shows (facts, with links),
  * what the model inferred,
  * what remains an assumption.

It also states the real scope of the data: which platforms were reached,
which were not and why, and how many distinct authors are actually behind
the findings.
"""
from __future__ import annotations

import json
from typing import Optional

from . import db
from .cluster import cluster_evidence, list_clusters
from .competitors import ABSENCE_DISCLAIMER, list_competitors
from .evaluate import list_opportunities
from .review import list_tasks
from .store import counts, get_project, latest_run, steps


def _access_summary(conn, project_id: str) -> list[dict]:
    rows = db.rows(conn,
        "SELECT platform, status, COUNT(*) n, MAX(created_at) last_at,"
        " MAX(COALESCE(reason,'')) reason, MAX(COALESCE(http_code,0)) code"
        " FROM access_attempts WHERE project_id=? GROUP BY platform, status"
        " ORDER BY platform, status", (project_id,))
    return [dict(r) for r in rows]


def build_report(conn, project_id: str, data_origin: str = db.REAL) -> dict:
    p = get_project(conn, project_id)
    if p is None:
        raise ValueError("unknown project")
    run = latest_run(conn, project_id)
    cl = list_clusters(conn, project_id, data_origin=data_origin)
    opps = list_opportunities(conn, project_id, data_origin=data_origin)
    comps = list_competitors(conn, project_id, data_origin=data_origin)
    tasks = list_tasks(conn, project_id)
    qrows = db.rows(conn, "SELECT platform, lang, status, COUNT(*) n FROM search_queries"
                          " WHERE project_id=? GROUP BY platform, lang, status", (project_id,))
    authors = db.one(conn, "SELECT COUNT(DISTINCT s.author_ref) FROM sources s"
                           " WHERE s.project_id=? AND s.data_origin=? AND s.author_ref IS NOT NULL",
                     (project_id, data_origin))
    plats = db.rows(conn, "SELECT platform, COUNT(*) n FROM sources WHERE project_id=? AND"
                          " data_origin=? GROUP BY platform ORDER BY n DESC",
                    (project_id, data_origin))

    clusters_out = []
    for c in cl:
        ev = cluster_evidence(conn, c["id"])
        clusters_out.append({
            "id": c["id"], "label": c["label"], "problem_statement": c["problem_statement"],
            "audience": c["audience"], "existing_solutions": c["existing_solutions"],
            "impacts": c["impacts"], "knowledge_gaps": c["knowledge_gaps"],
            "contradicting_evidence": c["contradicting"],
            "distinct_signals": c["distinct_sources"], "distinct_authors": c["distinct_authors"],
            "evidence": [{
                "quote": e["quote"], "pain_type": e["pain_type"], "clarity": e["clarity"],
                "platform": e["platform"], "url": e["url"], "author_ref": e["author_ref"],
                "published_at": e["published_at"], "found_by_query": e["found_by_query"],
                "extraction_method": e["extraction_method"],
                "evidence_limits": e["evidence_limits"],
                "verification_status": e["verification_status"],
            } for e in ev],
        })

    return {
        "generated_at": db.now(),
        "data_origin": data_origin,
        "project": {k: p[k] for k in p.keys()},
        "run": ({k: run[k] for k in run.keys()} if run else None),
        "run_steps": [{k: s[k] for k in s.keys()} for s in (steps(conn, run["id"]) if run else [])],
        "counts": counts(conn, project_id, data_origin=data_origin),
        "data_scope": {
            "platforms_with_data": [dict(r) for r in plats],
            "distinct_public_authors": (authors[0] if authors else 0),
            "queries_by_platform_lang_status": [dict(r) for r in qrows],
            "access_attempts": _access_summary(conn, project_id),
        },
        "problem_clusters": clusters_out,
        "competitors": [{k: c[k] for k in c.keys()} for c in comps],
        "competitor_absence_disclaimer": ABSENCE_DISCLAIMER,
        "opportunities": [{
            **{k: o[k] for k in o.keys() if k not in ("rubric_json", "assumptions",
                                                      "facts", "inferences", "next_experiments")},
            "facts": db.jload(o["facts"], []),
            "inferences": db.jload(o["inferences"], []),
            "assumptions": db.jload(o["assumptions"], []),
            "next_experiments": db.jload(o["next_experiments"], []),
            "rubric": db.jload(o["rubric_json"], {}),
        } for o in opps],
        "human_tasks": [{k: t[k] for k in t.keys()} for t in tasks],
        "limits": _limits(conn, project_id, data_origin),
    }


def _limits(conn, project_id: str, data_origin: str) -> list[str]:
    out = [
        "Scores are a heuristic ranking under declared rules. They are NOT probabilities of "
        "commercial success and must not be read as such.",
        "Evidence strength reflects only the sample actually collected. The sample is biased "
        "toward the platforms that were reachable and the queries that were executed.",
        "Post counts are not user counts. 'distinct_authors' is reported separately and is the "
        "number that matters for any claim about a pattern.",
        "Willingness-to-pay entries record language only. No payment or transaction was observed.",
        ABSENCE_DISCLAIMER,
    ]
    blocked = db.rows(conn, "SELECT DISTINCT platform, status, MAX(COALESCE(reason,'')) r"
                            " FROM access_attempts WHERE project_id=? AND status!='ok'"
                            " GROUP BY platform, status", (project_id,))
    for b in blocked:
        out.append(f"Source '{b['platform']}' was not collected ({b['status']}): {b['r'][:160]}")
    syn = db.one(conn, "SELECT COUNT(*) FROM contents WHERE project_id=? AND data_origin=?",
                 (project_id, db.SYNTHETIC))
    if syn and syn[0]:
        out.append(f"NOTE: this project also holds {syn[0]} synthetic test row(s). They are "
                   f"excluded from this report (data_origin='{data_origin}').")
    return out


# ------------------------------------------------------------------ markdown

def to_markdown(rep: dict) -> str:
    p, L = rep["project"], []
    a = L.append
    a(f"# Opportunity Discovery Report - {p['name']}")
    a("")
    a(f"- **Domain:** {p['domain']}")
    a(f"- **Market:** {p.get('market') or 'not specified'}")
    a(f"- **Languages:** {p.get('languages')}")
    a(f"- **Generated:** {rep['generated_at']}")
    a(f"- **Data origin:** `{rep['data_origin']}`"
      + ("  _(real collected/imported data only)_" if rep["data_origin"] == "real"
         else "  _(SYNTHETIC TEST DATA - not market evidence)_"))
    if rep.get("run"):
        a(f"- **Run:** `{rep['run']['id']}` status=`{rep['run']['status']}`")
    a("")

    c = rep["counts"]
    a("## 1. What was actually collected")
    a("")
    a("| metric | value |")
    a("|---|---|")
    for k in ("queries", "sources", "contents", "signals", "signals_dup",
              "clusters", "competitors", "opportunities", "open_tasks"):
        a(f"| {k} | {c.get(k, 0)} |")
    a(f"| distinct public authors | {rep['data_scope']['distinct_public_authors']} |")
    a("")
    a("**Platforms with collected data**")
    a("")
    if rep["data_scope"]["platforms_with_data"]:
        a("| platform | records |")
        a("|---|---|")
        for r in rep["data_scope"]["platforms_with_data"]:
            a(f"| {r['platform']} | {r['n']} |")
    else:
        a("_No data collected yet._")
    a("")
    a("**Access attempts (successes and failures)**")
    a("")
    a("| platform | status | n | http | reason |")
    a("|---|---|---|---|---|")
    for r in rep["data_scope"]["access_attempts"]:
        a(f"| {r['platform']} | `{r['status']}` | {r['n']} | {r['code'] or ''} | "
          f"{(r['reason'] or '')[:110].replace('|','/')} |")
    a("")

    a("## 2. Problem clusters (evidence-backed)")
    a("")
    if not rep["problem_clusters"]:
        a("_No clusters._")
    for i, cl in enumerate(rep["problem_clusters"], 1):
        a(f"### 2.{i} {cl['label']}")
        a("")
        a(f"- **Core problem (highest-clarity quote):** {cl['problem_statement']}")
        a(f"- **Audience named in evidence:** {cl['audience']}")
        a(f"- **Current solutions observed:** {cl['existing_solutions']}")
        a(f"- **Quantified impacts in evidence:** {cl['impacts']}")
        a(f"- **Distinct signals / distinct authors:** {cl['distinct_signals']} / "
          f"**{cl['distinct_authors']}**")
        a(f"- **Knowledge gaps:** {cl['knowledge_gaps']}")
        a(f"- **Contradicting evidence:** {cl['contradicting_evidence']}")
        a("")
        a("**Evidence chain**")
        a("")
        for j, e in enumerate(cl["evidence"], 1):
            a(f"{j}. _\"{e['quote'][:300]}\"_")
            a(f"   - type=`{e['pain_type']}` clarity=`{e['clarity']}` "
              f"platform=`{e['platform']}` extraction=`{e['extraction_method']}`")
            a(f"   - source: {e['url'] or '(no url - manual import)'}"
              f"  author: `{e['author_ref'] or 'n/a'}`  published: `{e['published_at'] or 'n/a'}`")
            a(f"   - found by query: `{e['found_by_query'] or 'manual import'}`")
            a(f"   - **limits:** {e['evidence_limits']}")
            a(f"   - verification: `{e['verification_status']}`")
        a("")

    a("## 3. Competitors / existing solutions named in evidence")
    a("")
    if rep["competitors"]:
        a("| name | mentions | pricing (verbatim) | pricing source |")
        a("|---|---|---|---|")
        for cp in rep["competitors"]:
            a(f"| {cp['name']} | {cp['mention_count']} | {cp['pricing_text'] or '-'} | "
              f"{cp['pricing_evidence_url'] or '-'} |")
        a("")
        for cp in rep["competitors"]:
            if cp["complaints"] and cp["complaints"] != "none captured in this sample":
                a(f"**Complaints about {cp['name']}**")
                a("")
                for line in str(cp["complaints"]).split("\n")[:6]:
                    a(f"- {line}")
                a("")
    else:
        a("_None named in the collected evidence._")
        a("")
    a(f"> {rep['competitor_absence_disclaimer']}")
    a("")

    a("## 4. Opportunity hypotheses")
    a("")
    a("> Scores are a heuristic ranking under declared rules, not probabilities of success. "
      "`evidence` and `attractiveness` are deliberately separate.")
    a("")
    for i, o in enumerate(rep["opportunities"], 1):
        a(f"### 4.{i} {o['title']}")
        a("")
        a(f"- **Evidence strength:** {o['evidence_strength']} "
          f"({o['rubric'].get('evidence_raw','')})")
        a(f"- **Attractiveness (judgment):** {o['attractiveness']} "
          f"({o['rubric'].get('attractiveness_raw','')})")
        a(f"- **Hypothesis:** {o['hypothesis']}")
        a("")
        a("**FACTS (from evidence)**")
        a("")
        for f in o["facts"]:
            a(f"- {f}")
        a("")
        a("**INFERENCES (model reasoning, not evidence)**")
        a("")
        for f in o["inferences"]:
            a(f"- {f}")
        a("")
        a("**ASSUMPTIONS (unverified)**")
        a("")
        for f in o["assumptions"]:
            a(f"- {f}")
        a("")
        a("**Scoring detail**")
        a("")
        a("| criterion | score | rule | basis |")
        a("|---|---|---|---|")
        for k, v in (o["rubric"].get("criteria") or {}).items():
            a(f"| {k} | {v['score']}/{v['max']} | {v['rule'][:90].replace('|','/')} | "
              f"{str(v['basis'])[:150].replace('|','/')} |")
        a("")
        a("**Next validation experiments**")
        a("")
        for f in o["next_experiments"]:
            a(f"- [ ] {f}")
        a("")

    a("## 5. Human review tasks")
    a("")
    if rep["human_tasks"]:
        for t in rep["human_tasks"]:
            a(f"### [{t['status']}] {t['title']}")
            a("")
            a(f"- **Kind:** `{t['kind']}`")
            a(f"- **What is needed:** {t['what_is_needed']}")
            a(f"- **Why the system needs you:** {t['why_needed']}")
            a(f"- **Steps:**")
            for line in str(t["steps"]).split("\n"):
                a(f"  - {line}")
            a(f"- **What to return:** {t['expected_return']}")
            a(f"- **What happens next:** {t['after_completion']}")
            if t["response_text"]:
                a(f"- **Your response:** {t['response_text'][:500]}")
            a("")
    else:
        a("_None._")
        a("")

    a("## 6. Limits of this report")
    a("")
    for l in rep["limits"]:
        a(f"- {l}")
    a("")
    return "\n".join(L)


def export(conn, project_id: str, out_dir: str, data_origin: str = db.REAL) -> dict:
    import os
    rep = build_report(conn, project_id, data_origin=data_origin)
    os.makedirs(out_dir, exist_ok=True)
    tag = "" if data_origin == db.REAL else "_SYNTHETIC"
    jp = os.path.join(out_dir, f"report_{project_id}{tag}.json")
    mp = os.path.join(out_dir, f"report_{project_id}{tag}.md")
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)
    with open(mp, "w", encoding="utf-8") as f:
        f.write(to_markdown(rep))
    return {"json": jp, "markdown": mp,
            "clusters": len(rep["problem_clusters"]),
            "opportunities": len(rep["opportunities"])}
