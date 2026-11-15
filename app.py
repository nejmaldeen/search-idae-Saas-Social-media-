"""Streamlit review UI for the AI SaaS Opportunity Discovery Agent.

Run:  streamlit run app.py
Design priority is correctness of what is shown, not visual polish:
  * real vs synthetic data is labelled everywhere;
  * every problem is shown with its evidence chain and limits;
  * sources that could not be reached are visible, with their reason.
"""
from __future__ import annotations

import json
import os
import sys

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from oda import db, orchestrator, report as report_mod, review, store   # noqa: E402
from oda.cluster import cluster_evidence, list_clusters                 # noqa: E402
from oda.competitors import (ABSENCE_DISCLAIMER, add_competitor,        # noqa: E402
                             list_competitors)
from oda.connectors import capability_table, get                        # noqa: E402
from oda.evaluate import list_opportunities                             # noqa: E402
from oda.queries import list_queries                                    # noqa: E402

st.set_page_config(page_title="Opportunity Discovery Agent", layout="wide")


@st.cache_resource
def _conn():
    return db.open_db(os.environ.get("ODA_DB", db.DEFAULT_DB))


conn = _conn()


def origin_badge(origin: str) -> str:
    return ("🟢 REAL DATA" if origin == db.REAL
            else "🧪 SYNTHETIC TEST DATA — not market evidence")


# ----------------------------------------------------------------- sidebar
st.sidebar.title("🔎 Opportunity Agent")
projects = store.list_projects(conn, include_synthetic=True)
labels = {f"{p['name']} [{p['id'][:10]}]": p["id"] for p in projects}

with st.sidebar.expander("➕ New research project", expanded=not projects):
    with st.form("new_project"):
        n_name = st.text_input("Project name", "AI SaaS opportunities")
        n_domain = st.text_input("Domain / niche *", "ecommerce inventory and order management")
        n_market = st.selectbox("Market", ["", "sa", "ae", "eg"], index=1)
        n_langs = st.multiselect("Languages", ["ar", "en"], default=["ar", "en"])
        n_sector = st.selectbox("Synonym pack", ["", "ecommerce", "saas"], index=1)
        n_period = st.number_input("Period (days)", 30, 3650, 365)
        if st.form_submit_button("Create") and n_domain.strip():
            pid = store.create_project(conn, name=n_name, domain=n_domain,
                                       market=n_market or None,
                                       languages=",".join(n_langs) or "en",
                                       period_days=int(n_period), notes=n_sector or None)
            st.success(f"Created {pid}")
            st.rerun()

if not projects:
    st.info("Create a research project in the sidebar to begin.")
    st.stop()

chosen = st.sidebar.selectbox("Project", list(labels))
pid = labels[chosen]
project = store.get_project(conn, pid)
origin = db.REAL if project["data_origin"] == db.REAL else db.SYNTHETIC

st.sidebar.markdown(f"**Data origin:** {origin_badge(origin)}")
c = store.counts(conn, pid, data_origin=origin)
st.sidebar.metric("Collected documents", c["contents"])
st.sidebar.metric("Unique pain signals", c["signals"])
st.sidebar.metric("Problem clusters", c["clusters"])
st.sidebar.metric("Open human tasks", c["open_tasks"])

# ------------------------------------------------------------------- header
st.title(project["name"])
st.caption(f"Domain: **{project['domain']}** · Market: **{project['market'] or 'n/a'}** · "
           f"Languages: **{project['languages']}** · {origin_badge(origin)}")

run = store.latest_run(conn, pid)
if run:
    st.caption(f"Latest run `{run['id']}` — status **{run['status']}** (created {run['created_at']})")

tabs = st.tabs(["① Feasibility", "② Run & Resume", "③ Queries", "④ Problems & Evidence",
                "⑤ Competitors", "⑥ Opportunities", "⑦ Human tasks",
                "⑧ Manual import", "⑨ Report"])

# ---------------------------------------------------------------- 1 feasibility
with tabs[0]:
    st.subheader("Source feasibility audit")
    st.caption("`code_supported` = the connector exists. `usable_now` = this machine really has "
               "the credentials and network to use it. They are deliberately different things.")
    do_probe = st.checkbox("Live reachability probe (slower)", value=False)
    rows = capability_table(probe=do_probe)
    st.dataframe([{
        "platform": r["platform"], "usable_now": r["usable_now"],
        "code_supported": r["code_supported"],
        "access_mechanism": r["access_mechanism"],
        "credentials": r["credentials_required"],
        "blocker": r["blocked_reason"] or "",
    } for r in rows], width='stretch', hide_index=True)
    for r in rows:
        with st.expander(f"{r['platform']} — details"):
            st.write(f"**Data available:** {r['data_available']}")
            st.write(f"**Limits:** {r['limits']}")
            st.write(f"**ToS notes:** {r['tos_notes']}")
            st.write(f"**Needs human:** {r['needs_human'] or '—'}")

# --------------------------------------------------------------- 2 run/resume
with tabs[1]:
    st.subheader("Run or resume the research pipeline")
    usable = [r["platform"] for r in capability_table() if r["usable_now"] and r["platform"] != "manual"]
    sel = st.multiselect("Platforms to collect from", usable, default=usable)
    col1, col2, col3 = st.columns(3)
    limit = col1.number_input("Results per query", 5, 100, 25)
    maxq = col2.number_input("Queries per platform", 1, 40, 8)
    sleep = col3.number_input("Seconds between queries", 0.0, 30.0, 7.0)
    tools = st.text_input("Known competitor/tool names (comma separated)",
                          "Shopify, Salla, Zid, Zoho Inventory")
    resume = st.checkbox("Resume (skip already-completed steps)", value=True)

    if st.button("▶ Run pipeline", type="primary"):
        with st.spinner("Running… collection respects provider rate limits."):
            rep = orchestrator.run_pipeline(
                conn, pid, platforms=sel or None, resume=resume,
                sector=project["notes"], per_query_limit=int(limit),
                max_queries_per_platform=int(maxq), sleep_between=float(sleep),
                known_tools=[t.strip() for t in tools.split(",") if t.strip()])
        st.success(f"Run {rep['run_id']} — status {rep['run_status']}")
        st.json(rep["steps"])

    if run:
        st.markdown("#### Step state (resume points)")
        st.dataframe([{
            "step": s["step_name"], "status": s["status"],
            "started": s["started_at"], "finished": s["finished_at"],
            "error": s["error"] or "",
        } for s in store.steps(conn, run["id"])], width='stretch', hide_index=True)

    st.markdown("#### Access attempts (including failures)")
    aa = db.rows(conn, "SELECT platform,status,COUNT(*) n,MAX(COALESCE(http_code,0)) code,"
                       "MAX(COALESCE(reason,'')) reason FROM access_attempts WHERE project_id=?"
                       " GROUP BY platform,status", (pid,))
    if aa:
        st.dataframe([dict(r) for r in aa], width='stretch', hide_index=True)
    else:
        st.caption("No collection attempted yet.")

# ------------------------------------------------------------------ 3 queries
with tabs[2]:
    st.subheader("Generated search queries")
    qs = list_queries(conn, pid)
    st.caption(f"{len(qs)} queries. Every query that ran is stored with its platform, "
               "language, execution time and result count.")
    st.dataframe([{
        "platform": q["platform"], "lang": q["lang"], "intent": q["intent"],
        "status": q["status"], "results": q["result_count"],
        "executed_at": q["executed_at"] or "", "query": q["text"],
        "error": (q["error"] or "")[:80],
    } for q in qs], width='stretch', hide_index=True)

# -------------------------------------------------------- 4 problems/evidence
with tabs[3]:
    st.subheader("Problem clusters and their evidence chain")
    cls = list_clusters(conn, pid, data_origin=origin)
    if not cls:
        st.info("No clusters yet. Collect or import content, then run the pipeline.")
    for cl in cls:
        strong = (cl["distinct_authors"] or 0) >= orchestrator.WEAK_EVIDENCE_AUTHORS
        with st.expander(f"{'✅' if strong else '⚠️'} {cl['label']} — "
                         f"{cl['distinct_authors']} distinct author(s)"):
            st.write(f"**Core problem (highest-clarity quote):** {cl['problem_statement']}")
            a, b = st.columns(2)
            a.write(f"**Audience in evidence:** {cl['audience']}")
            a.write(f"**Current solutions:** {cl['existing_solutions']}")
            b.write(f"**Quantified impacts:** {cl['impacts']}")
            b.write(f"**Signals / authors:** {cl['distinct_sources']} / {cl['distinct_authors']}")
            st.warning(f"**Knowledge gaps:** {cl['knowledge_gaps']}")
            st.info(f"**Contradicting evidence:** {cl['contradicting']}")
            st.markdown("**Evidence**")
            for e in cluster_evidence(conn, cl["id"]):
                st.markdown(
                    f"> {e['quote'][:420]}\n\n"
                    f"`{e['pain_type']}` clarity `{e['clarity']}` · platform `{e['platform']}` · "
                    f"extraction `{e['extraction_method']}` · author `{e['author_ref'] or 'n/a'}`\n\n"
                    f"source: {e['url'] or '(manual import — no URL)'}\n\n"
                    f"found by query: `{e['found_by_query'] or 'manual import'}`")
                st.caption(f"Limits: {e['evidence_limits']}")
                st.divider()

# -------------------------------------------------------------- 5 competitors
with tabs[4]:
    st.subheader("Competitors / existing solutions")
    st.error(ABSENCE_DISCLAIMER)
    comps = list_competitors(conn, pid, data_origin=origin)
    if comps:
        st.dataframe([{
            "name": x["name"], "mentions": x["mention_count"],
            "pricing (verbatim)": x["pricing_text"] or "—",
            "pricing source": x["pricing_evidence_url"] or "—",
            "gaps": (x["gaps"] or "")[:90],
        } for x in comps], width='stretch', hide_index=True)
        for x in comps:
            if x["complaints"] and x["complaints"] != "none captured in this sample":
                with st.expander(f"Complaints about {x['name']}"):
                    st.text(x["complaints"])
    else:
        st.caption("None named in the collected evidence.")
    with st.expander("➕ Add a competitor from your own review"):
        with st.form("add_comp"):
            cn = st.text_input("Name *")
            cu = st.text_input("URL")
            cp = st.text_input("Pricing (copy verbatim)")
            cpu = st.text_input("Pricing source URL")
            cf = st.text_area("Features observed")
            cc = st.text_area("Complaints observed")
            if st.form_submit_button("Add") and cn.strip():
                add_competitor(conn, pid, cn.strip(), url=cu or None, pricing_text=cp or None,
                               pricing_evidence_url=cpu or None, features=cf or None,
                               complaints=cc or None, data_origin=origin)
                st.success("Added")
                st.rerun()

# ------------------------------------------------------------ 6 opportunities
with tabs[5]:
    st.subheader("Opportunity hypotheses")
    st.warning("Scores are a **heuristic ranking under declared rules**, not probabilities of "
               "commercial success. Evidence strength and attractiveness are kept separate on purpose.")
    opps = list_opportunities(conn, pid, data_origin=origin)
    if not opps:
        st.info("No opportunities yet.")
    for o in opps:
        with st.expander(f"{o['title']} — evidence {o['evidence_strength']} / "
                         f"attractiveness {o['attractiveness']}"):
            rub = db.jload(o["rubric_json"], {})
            m1, m2 = st.columns(2)
            m1.metric("Evidence strength", f"{o['evidence_strength']}",
                      help=f"raw {rub.get('evidence_raw','')}")
            m2.metric("Attractiveness (judgment)", f"{o['attractiveness']}",
                      help=f"raw {rub.get('attractiveness_raw','')}")
            st.write(f"**Hypothesis:** {o['hypothesis']}")
            f1, f2, f3 = st.columns(3)
            with f1:
                st.markdown("**FACTS** _(from evidence)_")
                for x in db.jload(o["facts"], []):
                    st.markdown(f"- {x}")
            with f2:
                st.markdown("**INFERENCES** _(model reasoning)_")
                for x in db.jload(o["inferences"], []):
                    st.markdown(f"- {x}")
            with f3:
                st.markdown("**ASSUMPTIONS** _(unverified)_")
                for x in db.jload(o["assumptions"], []):
                    st.markdown(f"- {x}")
            st.markdown("**Scoring detail**")
            st.dataframe([{"criterion": k, "score": f"{v['score']}/{v['max']}",
                           "rule": v["rule"], "basis": v["basis"]}
                          for k, v in (rub.get("criteria") or {}).items()],
                         width='stretch', hide_index=True)
            st.markdown("**Next validation experiments**")
            for x in db.jload(o["next_experiments"], []):
                st.checkbox(x, key=f"exp_{o['id']}_{hash(x)}", value=False)

# ------------------------------------------------------------- 7 human tasks
with tabs[6]:
    st.subheader("Human review tasks")
    flt = st.radio("Show", ["open", "completed", "all"], horizontal=True)
    tasks = review.list_tasks(conn, pid, status=None if flt == "all" else flt)
    if not tasks:
        st.success("No tasks in this view.")
    for t in tasks:
        icon = {"open": "🔴", "completed": "✅", "dismissed": "⚪", "in_progress": "🟡"}.get(t["status"], "•")
        with st.expander(f"{icon} [{t['kind']}] {t['title']}"):
            st.write(f"**What is needed:** {t['what_is_needed']}")
            st.write(f"**Why the system needs you:** {t['why_needed']}")
            st.write("**Steps:**")
            st.text(t["steps"])
            st.write(f"**What to return:** {t['expected_return']}")
            st.write(f"**What happens next:** {t['after_completion']}")
            if t["status"] == "open":
                with st.form(f"ans_{t['id']}"):
                    resp = st.text_area("Your response / findings", key=f"r_{t['id']}")
                    c1, c2 = st.columns(2)
                    if c1.form_submit_button("✅ Complete task"):
                        ok, msg = review.complete_task(conn, t["id"], resp)
                        (st.success if ok else st.error)(msg)
                        if ok:
                            st.rerun()
                    if c2.form_submit_button("⚪ Dismiss"):
                        review.dismiss_task(conn, t["id"], "dismissed in UI")
                        st.rerun()
            elif t["response_text"]:
                st.info(f"**Your response:** {t['response_text']}")

# ----------------------------------------------------------- 8 manual import
with tabs[7]:
    st.subheader("Manual import — real content you are entitled to access")
    st.caption("This is the path for platforms with no usable API (TikTok, Instagram, X, G2, "
               "Capterra). Accepts JSONL, a JSON list, CSV with a `text` column, or plain text "
               "blocks separated by a blank line or `---`.")
    st.info("Platform text is stored as **untrusted data** and is never executed as instructions.")
    ip_platform = st.text_input("Origin platform label", "tiktok")
    ip_kind = st.selectbox("Content kind", ["comment", "post", "review", "transcript", "note"])
    as_synth = st.checkbox("Mark as SYNTHETIC test data (excluded from real reports)",
                           value=(origin == db.SYNTHETIC))
    payload = st.text_area("Paste content", height=260,
                           placeholder='{"text": "...", "url": "https://...", "author": "..."}\n'
                                       'or plain text blocks separated by a blank line')
    upl = st.file_uploader("…or upload a file", type=["txt", "json", "jsonl", "csv", "tsv"])
    if upl is not None:
        payload = upl.read().decode("utf-8", errors="replace")
        st.caption(f"Loaded {len(payload)} characters from {upl.name}")
    if st.button("⬆ Import", type="primary") and payload.strip():
        res = get("manual").parse(payload, default_platform=ip_platform, default_kind=ip_kind)
        stt = store.ingest_result(conn, pid, ip_platform, res,
                                  data_origin=db.SYNTHETIC if as_synth else db.REAL)
        st.success(f"Imported: {stt['new_contents']} new, {stt['duplicate_contents']} duplicate(s)")
        st.json(stt)
        st.caption("Now re-run the pipeline (tab ②) to extract, cluster and score the new evidence.")

# ------------------------------------------------------------------ 9 report
with tabs[8]:
    st.subheader("Report")
    which = st.radio("Data origin to report on", [db.REAL, db.SYNTHETIC], horizontal=True,
                     format_func=origin_badge)
    rep = report_mod.build_report(conn, pid, data_origin=which)
    md = report_mod.to_markdown(rep)
    c1, c2 = st.columns(2)
    c1.download_button("⬇ Download Markdown", md, file_name=f"report_{pid}.md")
    c2.download_button("⬇ Download JSON", json.dumps(rep, ensure_ascii=False, indent=2),
                       file_name=f"report_{pid}.json")
    if st.button("💾 Write both to ./exports"):
        st.json(report_mod.export(conn, pid, "exports", data_origin=which))
    st.markdown("#### Limits of this report")
    for l in rep["limits"]:
        st.markdown(f"- {l}")
    with st.expander("Full Markdown preview", expanded=False):
        st.markdown(md)
