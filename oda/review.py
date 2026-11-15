"""Human Review Manager.

A human task always answers five questions, because a vague ask wastes the
user's time: what is needed, why the system cannot do it, the steps, what to
return, and what happens next.

Completing a task stores the user's input, validates it, links it to the
research project and lets the run resume without re-collecting stored data.
"""
from __future__ import annotations

from typing import Optional

from . import db

KINDS = ("login", "manual_review", "export", "permission", "decision",
         "interview", "weak_evidence", "access_blocked")


def create_task(conn, project_id: str, kind: str, title: str, what_is_needed: str,
                why_needed: str, steps: str, expected_return: str, after_completion: str,
                run_id: Optional[str] = None, blocks_step: Optional[str] = None) -> str:
    tid = db.new_id("tsk")
    conn.execute(
        "INSERT INTO human_tasks(id,project_id,run_id,kind,title,what_is_needed,why_needed,steps,"
        "expected_return,after_completion,blocks_step,status,created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?, 'open', ?)",
        (tid, project_id, run_id, kind, title, what_is_needed, why_needed, steps,
         expected_return, after_completion, blocks_step, db.now()))
    conn.commit()
    db.log(conn, "info", "review", f"human task created: {title}",
           project_id=project_id, run_id=run_id, payload={"task_id": tid, "kind": kind})
    return tid


def task_for_access_failure(conn, project_id: str, platform: str, reason: str,
                            run_id: Optional[str] = None,
                            blocks_step: Optional[str] = None) -> str:
    """Raised whenever a connector cannot reach a source (AC-08)."""
    existing = db.one(conn,
        "SELECT id FROM human_tasks WHERE project_id=? AND kind='access_blocked'"
        " AND title LIKE ? AND status='open'", (project_id, f"%{platform}%"))
    if existing:
        return existing["id"]
    from .connectors import get
    conn_obj = get(platform)
    cap = conn_obj.capability if conn_obj else None
    needed = (", ".join(cap.credentials_required) if cap and cap.credentials_required else "n/a")
    mech = cap.access_mechanism if cap else "unknown"
    return create_task(
        conn, project_id, "access_blocked",
        title=f"Unblock data access for: {platform}",
        what_is_needed=(
            f"Either supply credentials ({needed}) and/or allow network access to the "
            f"{platform} API host, or export the relevant content manually and paste it "
            f"into the Manual Import tab."),
        why_needed=(
            f"The {platform} connector could not collect data. Recorded reason: {reason}. "
            f"The system will not scrape this platform or bypass its access controls, so it "
            f"cannot proceed on this source without you."),
        steps=(
            f"1) Access mechanism for this source: {mech}\n"
            f"2) If credentials are the blocker: create the app/API key and set {needed} "
            f"in the environment, then re-run collection.\n"
            f"3) If the network is the blocker: allow the API host in this environment's "
            f"network settings.\n"
            f"4) If neither is possible: open the platform in your browser, copy the relevant "
            f"posts/comments/reviews you are entitled to read, and use Manual Import "
            f"(JSONL/CSV/plain text all accepted)."),
        expected_return=("Either working credentials / network access, or pasted real content "
                         "with its source URLs where available."),
        after_completion=("Collection for this platform resumes. Already-stored content is not "
                          "re-collected; extraction, de-duplication, clustering and scoring re-run "
                          "over the combined evidence."),
        run_id=run_id, blocks_step=blocks_step)


def task_for_weak_evidence(conn, project_id: str, cluster_id: str, label: str,
                           gaps: str, run_id: Optional[str] = None) -> str:
    return create_task(
        conn, project_id, "weak_evidence",
        title=f"Review weak-evidence problem cluster: {label}",
        what_is_needed="Human judgment on whether this problem concept is worth pursuing.",
        why_needed=("The automated evidence for this cluster is thin, so the system will not "
                    f"present it as a validated finding. Recorded gaps: {gaps}"),
        steps=("1) Open the cluster and read each quote with its source link.\n"
               "2) Decide: real problem / not a problem / needs more data.\n"
               "3) If real, add any extra evidence you know of via Manual Import.\n"
               "4) Record your decision in the response box."),
        expected_return="A verdict plus the reasoning, and any added evidence.",
        after_completion=("Your verdict is stored against the cluster and shown in the report "
                          "next to the automated score, which is not overwritten."),
        run_id=run_id, blocks_step=cluster_id)


def task_for_transcript(conn, project_id: str, url: str, title: str,
                        run_id: Optional[str] = None) -> str:
    return create_task(
        conn, project_id, "manual_review",
        title=f"Review video content: {title[:70]}",
        what_is_needed="Watch the video and paste the parts where users describe a problem.",
        why_needed=("Caption download requires the video owner's OAuth, so the system has only "
                    "the title/description metadata, which is not what the video actually says."),
        steps=f"1) Open {url}\n2) Note any complaint, workaround or price objection.\n"
              f"3) Paste the relevant quotes into Manual Import with this URL as the source.",
        expected_return="Quoted statements plus the video URL and approximate timestamps.",
        after_completion="The quotes become evidence with full provenance and are re-clustered.",
        run_id=run_id)


def complete_task(conn, task_id: str, response_text: str,
                  response_json: Optional[dict] = None) -> tuple[bool, str]:
    """Store and validate a human response. Returns (ok, message)."""
    row = db.one(conn, "SELECT * FROM human_tasks WHERE id=?", (task_id,))
    if not row:
        return False, "task not found"
    if row["status"] == "completed":
        return False, "task already completed; nothing re-collected"
    if not (response_text or "").strip():
        return False, "response cannot be empty"
    conn.execute("UPDATE human_tasks SET status='completed', response_text=?, response_json=?,"
                 " completed_at=? WHERE id=?",
                 (response_text.strip(), db.jdump(response_json), db.now(), task_id))
    conn.commit()
    db.log(conn, "info", "review", f"human task completed: {row['title']}",
           project_id=row["project_id"], run_id=row["run_id"], payload={"task_id": task_id})
    return True, "response stored and linked to the project"


def dismiss_task(conn, task_id: str, reason: str = "") -> bool:
    cur = conn.execute("UPDATE human_tasks SET status='dismissed', response_text=?,"
                       " completed_at=? WHERE id=? AND status!='completed'",
                       (reason or "dismissed by user", db.now(), task_id))
    conn.commit()
    return bool(cur.rowcount)


def list_tasks(conn, project_id: str, status: Optional[str] = None) -> list:
    sql = "SELECT * FROM human_tasks WHERE project_id=?"
    params: list = [project_id]
    if status:
        sql += " AND status=?"
        params.append(status)
    return db.rows(conn, sql + " ORDER BY CASE status WHEN 'open' THEN 0 WHEN 'in_progress'"
                              " THEN 1 ELSE 2 END, created_at DESC", params)


def open_count(conn, project_id: str) -> int:
    r = db.one(conn, "SELECT COUNT(*) FROM human_tasks WHERE project_id=? AND status='open'",
               (project_id,))
    return r[0] if r else 0
