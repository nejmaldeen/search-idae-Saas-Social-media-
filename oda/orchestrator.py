"""Research Orchestrator.

One agent loop, plain functions, explicit steps. Each step records its status
so a run can stop (or crash, or be blocked on a human) and resume without
re-collecting stored data.

Pipeline:
  plan_queries -> collect -> extract -> dedupe -> cluster -> competitors
               -> evaluate -> review_gate
"""
from __future__ import annotations

import time
from typing import Iterable, Optional

from . import cluster as cluster_mod
from . import competitors as comp_mod
from . import db, evaluate, extract, queries, review, store
from .connectors import REGISTRY, capability_table, get

STEPS = ["plan_queries", "collect", "extract", "dedupe", "cluster",
         "competitors", "evaluate", "review_gate"]

WEAK_EVIDENCE_AUTHORS = 2   # clusters below this count as weak evidence
MAX_WEAK_EVIDENCE_TASKS = 5  # individual review tasks; the rest are summarised


# Signals below this clarity are not stored during automated collection.
MIN_SIGNAL_CLARITY = 0.45

# Words that are part of the domain but are far too common in ordinary English
# to prove relevance on their own: "in order to" is not an e-commerce signal.
# They still count inside a multi-word phrase ("order management").
GENERIC_ALONE = {
    "order", "orders", "management", "manage", "store", "stores", "product",
    "products", "service", "services", "system", "systems", "data", "business",
    "customer", "customers", "platform", "online", "site", "sites", "app", "apps",
}


def _domain_terms(project, sector: Optional[str] = None) -> list[str]:
    """Domain vocabulary used for relevance filtering: the domain phrase, its
    individual words, and the sector synonym pack (both languages)."""
    terms: list[str] = [project["domain"]]
    for t in (project["domain"] or "").replace("-", " ").split():
        if len(t) > 3:
            terms.append(t)
    key = (sector or project["notes"] or "").strip().lower()
    pack = queries.SYNONYMS.get(key, {})
    for lang_terms in pack.values():
        terms.extend(lang_terms)
        for phrase in lang_terms:
            for w in phrase.split():
                if len(w) > 3:
                    terms.append(w)
    seen, out = set(), []
    for t in terms:
        t = t.strip()
        if not t:
            continue
        # a single generic word is not evidence of domain relevance
        if " " not in t and t.lower() in GENERIC_ALONE:
            continue
        if t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out


def plan_queries(conn, project, run_id: str, platforms: Iterable[str],
                 sector: Optional[str] = None,
                 competitor_names: Iterable[str] = (),
                 max_per_platform: int = 24) -> dict:
    langs = [l.strip() for l in (project["languages"] or "ar,en").split(",") if l.strip()]
    qs = queries.expand(project["domain"], languages=langs, sector=sector,
                        market=project["market"], platforms=list(platforms),
                        competitor_names=list(competitor_names),
                        max_per_platform=max_per_platform)
    ids = queries.persist(conn, project["id"], qs, run_id=run_id)
    return {"planned": len(qs), "stored": len(ids),
            "by_lang": {l: sum(1 for q in qs if q["lang"] == l) for l in langs},
            "platforms": list(platforms)}


def collect(conn, project, run_id: str, platforms: Iterable[str],
            per_query_limit: int = 15, max_queries_per_platform: int = 6,
            sleep_between: float = 6.5, sector: Optional[str] = None,
            comments_per_post: int = 25, max_comment_posts: int = 8) -> dict:
    """Execute planned queries on each platform. Access failures raise human tasks.

    Queries are rendered per platform and, where the platform supports it,
    scoped to the communities/sites where the target audience actually talks.
    """
    out: dict = {"platforms": {}, "total_new_contents": 0, "access_failures": []}
    for platform in platforms:
        c = get(platform)
        if c is None:
            continue
        ok, why = c.available()
        if not ok:
            db.record_access(conn, platform, "not_authorized", project_id=project["id"],
                             run_id=run_id, reason=why)
            tid = review.task_for_access_failure(conn, project["id"], platform, why,
                                                 run_id=run_id, blocks_step="collect")
            out["access_failures"].append({"platform": platform, "reason": why, "task_id": tid})
            out["platforms"][platform] = {"status": "not_authorized", "reason": why,
                                          "new_contents": 0}
            continue

        pending = [q for q in queries.list_queries(conn, project["id"], platform=platform,
                                                   status="planned")][:max_queries_per_platform]
        agg = {"status": "ok", "queries_run": 0, "new_contents": 0,
               "duplicates": 0, "fetched": 0, "errors": []}
        # platform-specific scoping
        extra_variants: list[dict] = []
        if platform == "reddit":
            extra_variants = [{"subreddit": sr} for sr in queries.subreddits_for(sector)[:4]]
        elif platform == "stackexchange":
            extra_variants = [{"site": st} for st in queries.se_sites_for(sector)[:2]]
        else:
            # cost control for provider-backed two-stage platforms
            extra_variants = [{"comments_per_post": comments_per_post,
                               "max_comment_posts": max_comment_posts}]

        for i, q in enumerate(pending):
            rendered = queries.render_for_platform(
                q["text"], platform,
                term=(q["term"] if "term" in q.keys() else None))
            res = None
            for variant in extra_variants:
                r = c.search(rendered, limit=per_query_limit, **variant)
                if res is None:
                    res = r
                elif r.ok:
                    res.items.extend(r.items)
                    res.access_status = r.access_status if not res.ok else res.access_status
                if not r.ok:
                    res = r if res is None else res
                    break
            st = store.ingest_result(conn, project["id"], platform, res,
                                     query_id=q["id"], run_id=run_id)
            agg["queries_run"] += 1
            agg["fetched"] += st["fetched"]
            agg["new_contents"] += st["new_contents"]
            agg["duplicates"] += st["duplicate_contents"]
            if not res.ok:
                agg["errors"].append(f"{res.access_status}: {res.reason}")
                agg["status"] = res.access_status
                tid = review.task_for_access_failure(
                    conn, project["id"], platform, f"{res.access_status}: {res.reason}",
                    run_id=run_id, blocks_step="collect")
                out["access_failures"].append({"platform": platform,
                                               "reason": f"{res.access_status}: {res.reason}",
                                               "task_id": tid})
                if res.access_status in ("rate_limited", "network_blocked", "not_authorized"):
                    break
            if sleep_between and i < len(pending) - 1:
                time.sleep(sleep_between)   # respect provider rate limits
        out["platforms"][platform] = agg
        out["total_new_contents"] += agg["new_contents"]
    return out


def review_gate(conn, project, run_id: str, data_origin: str = db.REAL) -> dict:
    """Raise human tasks for clusters the evidence does not support.

    Only the most substantial weak clusters get their own task; the long tail is
    summarised into a single task so the review queue stays usable.
    """
    weak = [cl for cl in cluster_mod.list_clusters(conn, project["id"],
                                                   data_origin=data_origin)
            if (cl["distinct_authors"] or 0) < WEAK_EVIDENCE_AUTHORS]
    weak.sort(key=lambda c: (c["distinct_sources"] or 0), reverse=True)

    raised = []
    for cl in weak[:MAX_WEAK_EVIDENCE_TASKS]:
        tid = review.task_for_weak_evidence(conn, project["id"], cl["id"], cl["label"],
                                            cl["knowledge_gaps"] or "", run_id=run_id)
        raised.append({"cluster_id": cl["id"], "task_id": tid, "label": cl["label"]})

    tail = weak[MAX_WEAK_EVIDENCE_TASKS:]
    summary_task = None
    if tail:
        existing = db.one(conn, "SELECT id FROM human_tasks WHERE project_id=?"
                                " AND kind='weak_evidence' AND title LIKE 'Thin-evidence backlog%'"
                                " AND status='open'", (project["id"],))
        labels = "\n".join(f"- {c['label']} (signals={c['distinct_sources']},"
                            f" authors={c['distinct_authors']})" for c in tail[:40])
        if existing:
            conn.execute("UPDATE human_tasks SET what_is_needed=? WHERE id=?",
                         (f"Decide whether to widen collection for {len(tail)} thin "
                          f"cluster(s):\n{labels}", existing["id"]))
            conn.commit()
            summary_task = existing["id"]
        else:
            summary_task = review.create_task(
                conn, project["id"], "weak_evidence",
                title=f"Thin-evidence backlog: {len(tail)} cluster(s) below the evidence bar",
                what_is_needed=(f"Decide whether to widen collection for {len(tail)} thin "
                                f"cluster(s):\n{labels}"),
                why_needed=("Each of these rests on a single author, so none can be called a "
                            "market pattern. Rather than one review task per cluster, they are "
                            "grouped here. Widening collection is usually the cheaper fix."),
                steps=("1) Unblock at least one more platform (see the access_blocked tasks), or\n"
                       "2) Import real content you can access for this domain, then\n"
                       "3) Re-run the pipeline - clustering and scoring recompute over the "
                       "combined evidence."),
                expected_return="Either more evidence, or a decision to drop these clusters.",
                after_completion=("Re-running the pipeline re-clusters everything; clusters that "
                                  "reach 2+ distinct authors stop being flagged as thin."),
                run_id=run_id)
            raised.append({"cluster_id": None, "task_id": summary_task,
                           "label": f"backlog of {len(tail)}"})
    return {"weak_evidence_tasks": len(raised), "thin_clusters": len(weak),
            "summarised_in_backlog": len(tail), "details": raised[:10],
            "open_tasks": review.open_count(conn, project["id"])}


# A run in any of these states is continued rather than replaced when
# resume=True, so closing and reopening the app picks up where it stopped.
RESUMABLE = ("running", "blocked", "pending", "failed", "completed")


def run_pipeline(conn, project_id: str, platforms: Optional[Iterable[str]] = None,
                 run_id: Optional[str] = None, resume: bool = True,
                 sector: Optional[str] = None, known_tools: Iterable[str] = (),
                 per_query_limit: int = 15, max_queries_per_platform: int = 6,
                 sleep_between: float = 6.5, only_steps: Optional[Iterable[str]] = None,
                 probe: bool = True, data_origin: str = db.REAL,
                 comments_per_post: int = 25, max_comment_posts: int = 8) -> dict:
    """Execute (or resume) the research pipeline. Returns a per-step report."""
    project = store.get_project(conn, project_id)
    if project is None:
        raise ValueError(f"unknown project: {project_id}")

    if run_id is None:
        existing = store.latest_run(conn, project_id)
        if resume and existing and existing["status"] in RESUMABLE:
            run_id = existing["id"]
        else:
            run_id = store.start_run(conn, project_id, goal=f"discover AI SaaS opportunities in "
                                                            f"{project['domain']}")
    store.set_run_status(conn, run_id, "running")

    if platforms is None:
        from .connectors import searchable_platforms
        platforms = searchable_platforms(probe=probe) or []
    platforms = list(platforms)

    terms = _domain_terms(project, sector=sector)
    wanted = list(only_steps) if only_steps else STEPS
    report: dict = {"run_id": run_id, "project_id": project_id, "platforms": platforms,
                    "steps": {}, "skipped": []}
    # Collecting from a live source into a synthetic-origin run would mix the
    # two, so it is refused outright.
    if data_origin != db.REAL and platforms:
        raise ValueError("refusing to collect live data into a synthetic-origin run; "
                         "pass platforms=[] when data_origin is synthetic_fixture")

    for step in STEPS:
        if step not in wanted:
            continue
        if resume and store.step_status(conn, run_id, step) == "completed" and step != "collect":
            report["skipped"].append(step)
            report["steps"][step] = {"status": "skipped_already_completed"}
            continue
        store.step_begin(conn, run_id, step)
        try:
            if step == "plan_queries":
                res = plan_queries(conn, project, run_id,
                                   platforms=list(platforms) + ["manual"],
                                   sector=sector, competitor_names=known_tools)
            elif step == "collect":
                res = collect(conn, project, run_id, platforms,
                              per_query_limit=per_query_limit,
                              max_queries_per_platform=max_queries_per_platform,
                              sleep_between=sleep_between, sector=sector,
                              comments_per_post=comments_per_post,
                              max_comment_posts=max_comment_posts)
            elif step == "extract":
                res = extract.run_extraction(conn, project_id, domain_terms=terms,
                                             run_id=run_id, min_clarity=MIN_SIGNAL_CLARITY,
                                             require_domain_term=True,
                                             data_origin=data_origin,
                                             exclude_terms=queries.exclusions_for(
                                                 sector or project["notes"]))
            elif step == "dedupe":
                from . import dedupe
                res = dedupe.run_dedupe(conn, project_id, run_id=run_id,
                                        data_origin=data_origin)
            elif step == "cluster":
                res = cluster_mod.build_clusters(conn, project_id, run_id=run_id,
                                                 data_origin=data_origin)
            elif step == "competitors":
                res = comp_mod.run_competitor_scan(conn, project_id, known_tools=known_tools,
                                                   run_id=run_id, data_origin=data_origin)
            elif step == "evaluate":
                res = evaluate.build_opportunities(conn, project_id, run_id=run_id,
                                                   data_origin=data_origin)
            elif step == "review_gate":
                res = review_gate(conn, project, run_id, data_origin=data_origin)
            else:
                res = {}
            store.step_end(conn, run_id, step, "completed", output=res)
            report["steps"][step] = res
        except Exception as e:                       # a failing step must not lose prior results
            store.step_end(conn, run_id, step, "failed", error=f"{e.__class__.__name__}: {e}")
            report["steps"][step] = {"status": "failed", "error": f"{e.__class__.__name__}: {e}"}
            db.log(conn, "error", f"pipeline:{step}", str(e), project_id=project_id, run_id=run_id)

    open_tasks = review.open_count(conn, project_id)
    store.set_run_status(conn, run_id, "blocked" if open_tasks else "completed")
    report["counts"] = store.counts(conn, project_id, data_origin=data_origin)
    report["data_origin"] = data_origin
    report["open_human_tasks"] = open_tasks
    report["run_status"] = "blocked" if open_tasks else "completed"
    report["capability_table"] = capability_table(probe=False)
    return report


def resume_run(conn, project_id: str, **kw) -> dict:
    """Resume the most recent run, skipping completed steps."""
    run = store.latest_run(conn, project_id)
    return run_pipeline(conn, project_id, run_id=run["id"] if run else None, resume=True, **kw)
