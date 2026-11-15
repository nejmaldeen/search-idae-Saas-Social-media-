"""Full-path test: project -> import -> extract -> cluster -> score -> report,
plus resume, human tasks and real/synthetic isolation (AC-01..AC-12)."""
import json
import os

from oda import db, orchestrator, report as report_mod, review, store
from oda.cluster import cluster_evidence, list_clusters
from oda.competitors import list_competitors
from oda.connectors import get
from oda.evaluate import list_opportunities

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "synthetic_pain.jsonl")


def _import_fixture(conn, project, origin=db.SYNTHETIC):
    payload = open(FIXTURE, encoding="utf-8").read()
    res = get("manual").parse(payload, default_platform="manual", default_kind="comment")
    return store.ingest_result(conn, project, "manual", res, data_origin=origin)


def test_ac01_project_created_and_persisted(conn, project):
    p = store.get_project(conn, project)
    assert p["name"] == "test" and p["domain"] == "ecommerce inventory"
    assert project in [x["id"] for x in store.list_projects(conn)]


def test_ac02_bilingual_queries_generated(conn, project):
    p = store.get_project(conn, project)
    rid = store.start_run(conn, project, "goal")
    res = orchestrator.plan_queries(conn, p, rid, platforms=["github", "manual"],
                                    sector="ecommerce")
    assert res["stored"] > 0
    assert res["by_lang"]["ar"] > 0 and res["by_lang"]["en"] > 0


def test_ac03_manual_import_of_real_content_works(conn, project):
    st = _import_fixture(conn, project, origin=db.SYNTHETIC)
    assert st["new_contents"] == 5
    assert st["access_status"] == "ok"


def test_full_pipeline_on_fixture_produces_evidence_backed_output(conn, project):
    _import_fixture(conn, project, origin=db.SYNTHETIC)
    terms = ["inventory", "مخزون", "متجر", "stock", "orders", "طلبات"]
    from oda import cluster as cmod
    from oda import competitors as compmod
    from oda import dedupe, evaluate, extract
    extract.run_extraction(conn, project, domain_terms=terms,
                           data_origin=db.SYNTHETIC, require_domain_term=True)
    dedupe.run_dedupe(conn, project, data_origin=db.SYNTHETIC)
    cstats = cmod.build_clusters(conn, project, data_origin=db.SYNTHETIC)
    compmod.run_competitor_scan(conn, project, known_tools=["Zoho Inventory", "Shopify"],
                                data_origin=db.SYNTHETIC)
    ostats = evaluate.build_opportunities(conn, project, data_origin=db.SYNTHETIC)

    assert cstats["signals"] > 0, "fixture must yield signals"
    assert cstats["clusters"] > 0
    assert ostats["opportunities"] > 0

    # AC-04: every cluster is traceable to evidence with a source reference
    for cl in list_clusters(conn, project, data_origin=db.SYNTHETIC):
        ev = cluster_evidence(conn, cl["id"])
        assert ev, f"cluster {cl['id']} has no evidence"
        for e in ev:
            assert e["quote"].strip()
            assert e["evidence_limits"].strip()
            assert e["url"] or e["extraction_method"] == "user_supplied"

    # AC-07: facts / inferences / assumptions are separated and populated
    for o in list_opportunities(conn, project, data_origin=db.SYNTHETIC):
        facts = db.jload(o["facts"], [])
        infs = db.jload(o["inferences"], [])
        assums = db.jload(o["assumptions"], [])
        assert facts and infs and assums
        assert set(facts).isdisjoint(set(assums))
        rub = db.jload(o["rubric_json"], {})
        assert "NOT a probability" in rub["disclaimer"]
        for name, crit in rub["criteria"].items():
            assert crit["rule"] and crit["basis"], f"{name} lacks a declared rule/basis"
        assert db.jload(o["next_experiments"], []), "every opportunity needs next experiments"


def test_spam_fixture_is_excluded_from_signals(conn, project):
    _import_fixture(conn, project, origin=db.SYNTHETIC)
    from oda import extract
    extract.run_extraction(conn, project, domain_terms=["inventory"],
                           data_origin=db.SYNTHETIC, require_domain_term=True)
    quotes = " ".join(r["quote"] for r in db.rows(
        conn, "SELECT quote FROM pain_signals WHERE project_id=?", (project,)))
    assert "free consultation" not in quotes
    assert "lovely today" not in quotes


def test_ac08_blocked_source_logs_reason_and_creates_human_task(conn, project):
    p = store.get_project(conn, project)
    rid = store.start_run(conn, project, "goal")
    out = orchestrator.collect(conn, p, rid, platforms=["youtube"], sleep_between=0)
    assert out["platforms"]["youtube"]["status"] == "not_authorized"
    assert out["access_failures"], "a blocked source must produce an access failure record"
    tasks = review.list_tasks(conn, project, status="open")
    assert any(t["kind"] == "access_blocked" for t in tasks)
    t = [x for x in tasks if x["kind"] == "access_blocked"][0]
    for field in ("what_is_needed", "why_needed", "steps", "expected_return", "after_completion"):
        assert t[field].strip(), f"human task missing {field}"
    rows = db.rows(conn, "SELECT * FROM access_attempts WHERE project_id=? AND status!='ok'",
                   (project,))
    assert rows


def test_blocked_source_task_is_not_duplicated(conn, project):
    p = store.get_project(conn, project)
    rid = store.start_run(conn, project, "goal")
    orchestrator.collect(conn, p, rid, platforms=["youtube"], sleep_between=0)
    orchestrator.collect(conn, p, rid, platforms=["youtube"], sleep_between=0)
    tasks = [t for t in review.list_tasks(conn, project) if t["kind"] == "access_blocked"]
    assert len(tasks) == 1


def test_human_task_completion_stores_and_validates_response(conn, project):
    tid = review.create_task(conn, project, "decision", "t", "w", "y", "s", "e", "a")
    ok, msg = review.complete_task(conn, tid, "")
    assert not ok and "empty" in msg
    ok, msg = review.complete_task(conn, tid, "my finding: confirmed with 3 interviews")
    assert ok
    row = db.one(conn, "SELECT * FROM human_tasks WHERE id=?", (tid,))
    assert row["status"] == "completed" and "3 interviews" in row["response_text"]
    ok, msg = review.complete_task(conn, tid, "again")
    assert not ok and "already completed" in msg


def test_ac09_resume_skips_completed_steps_and_keeps_data(conn, project):
    _import_fixture(conn, project, origin=db.REAL)
    before = store.counts(conn, project)["contents"]
    r1 = orchestrator.run_pipeline(conn, project, platforms=[], sector="ecommerce",
                                   sleep_between=0, probe=False)
    assert store.counts(conn, project)["contents"] == before
    r2 = orchestrator.run_pipeline(conn, project, platforms=[], sector="ecommerce",
                                   resume=True, sleep_between=0, probe=False)
    assert r2["skipped"], "a resumed run must skip completed steps"
    assert store.counts(conn, project)["contents"] == before, "resume must not lose or re-add data"
    assert r1["run_id"] == r2["run_id"]


def test_failing_step_does_not_lose_previous_results(conn, project, monkeypatch):
    _import_fixture(conn, project, origin=db.REAL)
    from oda import cluster as cmod
    orchestrator.run_pipeline(conn, project, platforms=[], sector="ecommerce",
                              only_steps=["extract", "dedupe"], sleep_between=0, probe=False)
    sig_before = store.counts(conn, project)["signals"]
    assert sig_before > 0

    def boom(*a, **k):
        raise RuntimeError("simulated cluster failure")

    monkeypatch.setattr(cmod, "build_clusters", boom)
    rep = orchestrator.run_pipeline(conn, project, platforms=[], sector="ecommerce",
                                    only_steps=["cluster"], resume=False, sleep_between=0,
                                    probe=False)
    assert rep["steps"]["cluster"]["status"] == "failed"
    assert "simulated" in rep["steps"]["cluster"]["error"]
    assert store.counts(conn, project)["signals"] == sig_before, "prior results must survive"


def test_ac10_report_contains_problems_sources_opportunities_and_experiments(conn, project):
    _import_fixture(conn, project, origin=db.REAL)
    orchestrator.run_pipeline(conn, project, platforms=[], sector="ecommerce",
                              sleep_between=0, probe=False)
    rep = report_mod.build_report(conn, project, data_origin=db.REAL)
    assert rep["problem_clusters"] and rep["opportunities"]
    assert rep["data_scope"]["access_attempts"] is not None
    assert rep["limits"]
    md = report_mod.to_markdown(rep)
    for section in ["What was actually collected", "Problem clusters", "Competitors",
                    "Opportunity hypotheses", "Human review tasks", "Limits of this report"]:
        assert section in md, f"report missing section: {section}"
    assert "FACTS" in md and "INFERENCES" in md and "ASSUMPTIONS" in md
    assert "Next validation experiments" in md
    assert "not probabilities of success" in md


def test_report_export_writes_both_files(conn, project, tmp_path):
    _import_fixture(conn, project, origin=db.REAL)
    orchestrator.run_pipeline(conn, project, platforms=[], sector="ecommerce",
                              sleep_between=0, probe=False)
    out = report_mod.export(conn, project, str(tmp_path / "ex"), data_origin=db.REAL)
    assert os.path.exists(out["json"]) and os.path.exists(out["markdown"])
    data = json.load(open(out["json"], encoding="utf-8"))
    assert data["data_origin"] == db.REAL


def test_synthetic_data_never_appears_in_a_real_report(conn, project):
    """AC: synthetic fixtures must not contaminate real market results."""
    _import_fixture(conn, project, origin=db.SYNTHETIC)
    from oda import cluster as cmod
    from oda import dedupe, evaluate, extract
    for origin in (db.SYNTHETIC,):
        extract.run_extraction(conn, project, domain_terms=["inventory", "مخزون"],
                               data_origin=origin, require_domain_term=True)
        dedupe.run_dedupe(conn, project, data_origin=origin)
        cmod.build_clusters(conn, project, data_origin=origin)
        evaluate.build_opportunities(conn, project, data_origin=origin)

    real = report_mod.build_report(conn, project, data_origin=db.REAL)
    assert real["problem_clusters"] == []
    assert real["opportunities"] == []
    blob = json.dumps(real, ensure_ascii=False)
    assert "SYNTHETIC FIXTURE" not in blob
    assert "example.invalid" not in blob
    # and the real report must disclose that synthetic rows exist
    assert any("synthetic" in l.lower() for l in real["limits"])

    synth = report_mod.build_report(conn, project, data_origin=db.SYNTHETIC)
    assert synth["problem_clusters"], "synthetic report should show synthetic clusters"
    assert "SYNTHETIC" in report_mod.to_markdown(synth)


def test_competitor_absence_is_never_proof_of_no_competition(conn, project):
    rep_md = report_mod.to_markdown(report_mod.build_report(conn, project))
    assert "is NOT evidence that none exists" in rep_md


def test_ac12_no_write_actions_exist_on_connectors(conn, project):
    """No connector may post, message, follow or modify an account."""
    from oda.connectors import REGISTRY
    forbidden = ("post", "comment", "reply", "follow", "like", "send", "publish",
                 "delete", "update_profile", "dm")
    for name, c in REGISTRY.items():
        for attr in dir(c):
            if attr.startswith("_"):
                continue
            assert attr not in forbidden, f"{name} exposes a write action: {attr}"
