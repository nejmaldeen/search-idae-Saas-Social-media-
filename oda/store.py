"""Ingestion: turn connector results into sources + contents with provenance.

Idempotency: sources are keyed (project, platform, external_id); contents are
keyed (project, content_hash). Re-running a collection never duplicates rows,
which is what makes runs safely resumable.
"""
from __future__ import annotations

from typing import Optional

from . import db
from .connectors.base import FetchResult, RawItem
from .textutil import content_hash, detect_lang


def create_project(conn, name: str, domain: str, market: Optional[str] = None,
                   languages: str = "ar,en", period_days: Optional[int] = 365,
                   notes: Optional[str] = None, data_origin: str = db.REAL) -> str:
    assert data_origin in db.VALID_ORIGINS
    pid = db.new_id("prj")
    conn.execute(
        "INSERT INTO projects(id,name,domain,market,languages,period_days,notes,created_at,data_origin)"
        " VALUES(?,?,?,?,?,?,?,?,?)",
        (pid, name, domain, market, languages, period_days, notes, db.now(), data_origin),
    )
    conn.commit()
    db.log(conn, "info", "store", f"project created: {name}", project_id=pid)
    return pid


def get_project(conn, project_id: str):
    return db.one(conn, "SELECT * FROM projects WHERE id=?", (project_id,))


def list_projects(conn, include_synthetic: bool = False) -> list:
    sql = "SELECT * FROM projects"
    params: tuple = ()
    if not include_synthetic:
        sql += " WHERE data_origin=?"
        params = (db.REAL,)
    return db.rows(conn, sql + " ORDER BY created_at DESC", params)


def start_run(conn, project_id: str, goal: str, config: Optional[dict] = None) -> str:
    rid = db.new_id("run")
    conn.execute(
        "INSERT INTO research_runs(id,project_id,goal,status,config_json,created_at,updated_at)"
        " VALUES(?,?,?,'pending',?,?,?)",
        (rid, project_id, goal, db.jdump(config or {}), db.now(), db.now()),
    )
    conn.commit()
    return rid


def set_run_status(conn, run_id: str, status: str) -> None:
    conn.execute("UPDATE research_runs SET status=?, updated_at=? WHERE id=?",
                 (status, db.now(), run_id))
    conn.commit()


def latest_run(conn, project_id: str):
    return db.one(conn, "SELECT * FROM research_runs WHERE project_id=?"
                        " ORDER BY created_at DESC LIMIT 1", (project_id,))


# ---------------- run steps (resume support) ----------------

def step_status(conn, run_id: str, step: str) -> Optional[str]:
    row = db.one(conn, "SELECT status FROM run_steps WHERE run_id=? AND step_name=?", (run_id, step))
    return row["status"] if row else None


def step_begin(conn, run_id: str, step: str) -> None:
    conn.execute(
        "INSERT INTO run_steps(id,run_id,step_name,status,started_at) VALUES(?,?,?,'running',?)"
        " ON CONFLICT(run_id,step_name) DO UPDATE SET status='running', started_at=excluded.started_at,"
        " error=NULL",
        (db.new_id("stp"), run_id, step, db.now()),
    )
    conn.commit()


def step_end(conn, run_id: str, step: str, status: str = "completed",
             error: Optional[str] = None, output: Optional[dict] = None) -> None:
    conn.execute(
        "UPDATE run_steps SET status=?, finished_at=?, error=?, output_json=?"
        " WHERE run_id=? AND step_name=?",
        (status, db.now(), error, db.jdump(output), run_id, step),
    )
    conn.commit()


def steps(conn, run_id: str) -> list:
    return db.rows(conn, "SELECT * FROM run_steps WHERE run_id=? ORDER BY started_at", (run_id,))


# ---------------- ingestion ----------------

def ingest_item(conn, project_id: str, platform: str, item: RawItem,
                query_id: Optional[str] = None, access_status: str = "ok",
                data_origin: str = db.REAL) -> tuple[Optional[str], Optional[str], bool]:
    """Insert one item. Returns (source_id, content_id, was_new_content)."""
    assert data_origin in db.VALID_ORIGINS
    plat = (item.raw_meta or {}).get("import_platform") or platform

    eng = item.engagement or {}
    sid = db.new_id("src")
    cur = conn.execute(
        "INSERT INTO sources(id,project_id,query_id,platform,external_id,url,title,author_ref,"
        "published_at,discovered_at,access_status,raw_meta_json,"
        "views,likes,comments_count,shares,saves,author_followers,data_origin)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
        # Backfill provenance that an earlier, less complete run missed. Only
        # NULL fields are filled; existing values are never overwritten.
        " ON CONFLICT(project_id,platform,external_id) DO UPDATE SET"
        "   url=COALESCE(sources.url, excluded.url),"
        "   author_ref=COALESCE(sources.author_ref, excluded.author_ref),"
        "   title=COALESCE(sources.title, excluded.title),"
        "   published_at=COALESCE(sources.published_at, excluded.published_at),"
        # Engagement counts grow over time, so the newer, higher reading wins.
        "   views=MAX(COALESCE(sources.views,0), COALESCE(excluded.views,0)),"
        "   likes=MAX(COALESCE(sources.likes,0), COALESCE(excluded.likes,0)),"
        "   comments_count=MAX(COALESCE(sources.comments_count,0),"
        "                      COALESCE(excluded.comments_count,0)),"
        "   shares=MAX(COALESCE(sources.shares,0), COALESCE(excluded.shares,0)),"
        "   saves=MAX(COALESCE(sources.saves,0), COALESCE(excluded.saves,0)),"
        "   author_followers=MAX(COALESCE(sources.author_followers,0),"
        "                        COALESCE(excluded.author_followers,0))",
        (sid, project_id, query_id, plat, item.external_id, item.url, item.title,
         item.author_ref, item.published_at, db.now(), access_status,
         db.jdump(item.raw_meta),
         eng.get("views"), eng.get("likes"), eng.get("comments_count"),
         eng.get("shares"), eng.get("saves"), eng.get("author_followers"),
         data_origin),
    )
    row = db.one(conn, "SELECT id FROM sources WHERE project_id=? AND platform=? AND external_id=?",
                 (project_id, plat, item.external_id))
    if row:
        sid = row["id"]

    chash = content_hash(item.text)
    cid = db.new_id("cnt")
    cur = conn.execute(
        "INSERT INTO contents(id,project_id,source_id,kind,text,lang,char_len,content_hash,"
        "extraction_method,collected_at,data_origin)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(project_id,content_hash) DO NOTHING",
        (cid, project_id, sid, item.kind, item.text, detect_lang(item.text),
         len(item.text), chash, item.extraction_method, db.now(), data_origin),
    )
    was_new = bool(cur.rowcount)
    if not was_new:
        row = db.one(conn, "SELECT id FROM contents WHERE project_id=? AND content_hash=?",
                     (project_id, chash))
        cid = row["id"] if row else None
    conn.commit()
    return sid, cid, was_new


def ingest_result(conn, project_id: str, platform: str, result: FetchResult,
                  query_id: Optional[str] = None, run_id: Optional[str] = None,
                  data_origin: str = db.REAL) -> dict:
    """Ingest a FetchResult. Always records the access attempt, success or not."""
    db.record_access(conn, platform, result.access_status, project_id=project_id,
                     run_id=run_id, endpoint=result.endpoint,
                     http_code=result.http_code, reason=result.reason)
    stats = {"platform": platform, "access_status": result.access_status,
             "fetched": len(result.items), "new_contents": 0, "duplicate_contents": 0,
             "reason": result.reason}
    for item in result.items:
        _, cid, was_new = ingest_item(conn, project_id, platform, item,
                                      query_id=query_id,
                                      access_status=result.access_status,
                                      data_origin=data_origin)
        if cid and was_new:
            stats["new_contents"] += 1
        elif cid:
            stats["duplicate_contents"] += 1
    if query_id:
        conn.execute(
            "UPDATE search_queries SET status=?, executed_at=?, result_count=?, error=? WHERE id=?",
            ("executed" if result.ok else "failed", db.now(), len(result.items),
             None if result.ok else f"{result.access_status}: {result.reason}", query_id),
        )
        conn.commit()
    db.log(conn, "info" if result.ok else "warn", f"ingest:{platform}",
           f"{result.access_status} fetched={len(result.items)} new={stats['new_contents']}",
           project_id=project_id, run_id=run_id, payload=stats)
    return stats


def contents_for(conn, project_id: str, data_origin: str = db.REAL,
                 platform: Optional[str] = None, limit: Optional[int] = None) -> list:
    sql = ("SELECT c.*, s.platform, s.url, s.title AS src_title, s.author_ref, s.published_at"
           " FROM contents c JOIN sources s ON s.id=c.source_id"
           " WHERE c.project_id=? AND c.data_origin=?")
    params: list = [project_id, data_origin]
    if platform:
        sql += " AND s.platform=?"
        params.append(platform)
    sql += " ORDER BY c.collected_at"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return db.rows(conn, sql, params)


def counts(conn, project_id: str, data_origin: str = db.REAL) -> dict:
    q = lambda sql: (db.one(conn, sql, (project_id, data_origin)) or [0])[0]
    return {
        "sources": q("SELECT COUNT(*) FROM sources WHERE project_id=? AND data_origin=?"),
        "contents": q("SELECT COUNT(*) FROM contents WHERE project_id=? AND data_origin=?"),
        "signals": q("SELECT COUNT(*) FROM pain_signals WHERE project_id=? AND data_origin=? AND duplicate_of IS NULL"),
        "signals_dup": q("SELECT COUNT(*) FROM pain_signals WHERE project_id=? AND data_origin=? AND duplicate_of IS NOT NULL"),
        "clusters": q("SELECT COUNT(*) FROM clusters WHERE project_id=? AND data_origin=?"),
        "competitors": q("SELECT COUNT(*) FROM competitors WHERE project_id=? AND data_origin=?"),
        "opportunities": q("SELECT COUNT(*) FROM opportunities WHERE project_id=? AND data_origin=?"),
        "queries": (db.one(conn, "SELECT COUNT(*) FROM search_queries WHERE project_id=?", (project_id,)) or [0])[0],
        "open_tasks": (db.one(conn, "SELECT COUNT(*) FROM human_tasks WHERE project_id=? AND status='open'", (project_id,)) or [0])[0],
    }
