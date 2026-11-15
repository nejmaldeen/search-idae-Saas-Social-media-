"""SQLite storage layer: schema, migrations, connection helpers.

Hard rule enforced here: every row that can originate from collection carries
`data_origin` which is either 'real' or 'synthetic_fixture'. Report/readout
paths MUST filter on data_origin='real' unless explicitly asked otherwise.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from typing import Any, Iterable, Iterator, Optional

REAL = "real"
SYNTHETIC = "synthetic_fixture"
VALID_ORIGINS = (REAL, SYNTHETIC)

SCHEMA_VERSION = 3

_ORIGIN_CHECK = "CHECK (data_origin IN ('real','synthetic_fixture'))"

SCHEMA = f"""
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    domain TEXT NOT NULL,
    market TEXT,
    languages TEXT NOT NULL DEFAULT 'ar,en',
    period_days INTEGER,
    notes TEXT,
    created_at TEXT NOT NULL,
    data_origin TEXT NOT NULL DEFAULT 'real' {_ORIGIN_CHECK}
);

CREATE TABLE IF NOT EXISTS research_runs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    goal TEXT,
    status TEXT NOT NULL,            -- pending|running|blocked|completed|failed
    config_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS run_steps (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
    step_name TEXT NOT NULL,
    status TEXT NOT NULL,            -- pending|running|completed|failed|blocked|skipped
    started_at TEXT,
    finished_at TEXT,
    error TEXT,
    output_json TEXT,
    UNIQUE (run_id, step_name)
);

CREATE TABLE IF NOT EXISTS search_queries (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    run_id TEXT REFERENCES research_runs(id) ON DELETE SET NULL,
    text TEXT NOT NULL,
    lang TEXT NOT NULL,
    platform TEXT NOT NULL,
    intent TEXT,                     -- pain|alternative|help|tool|hashtag|generic
    term TEXT,                       -- the base domain/synonym term this was built from
    status TEXT NOT NULL DEFAULT 'planned',  -- planned|executed|failed|skipped
    executed_at TEXT,
    result_count INTEGER DEFAULT 0,
    error TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (project_id, text, platform)
);

CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    query_id TEXT REFERENCES search_queries(id) ON DELETE SET NULL,
    platform TEXT NOT NULL,
    external_id TEXT,
    url TEXT,
    title TEXT,
    author_ref TEXT,                 -- pseudonymous handle or hash; no PII beyond public handle
    published_at TEXT,
    discovered_at TEXT NOT NULL,
    access_status TEXT NOT NULL DEFAULT 'ok',  -- ok|partial|denied|not_authorized|error
    raw_meta_json TEXT,
    -- Engagement metrics: needed to measure how much interest a piece of
    -- content actually attracted. Stored as discrete columns so they can be
    -- ranked and filtered, not buried in JSON. NULL means "not reported by
    -- this platform", which is different from zero.
    views INTEGER,
    likes INTEGER,
    comments_count INTEGER,
    shares INTEGER,
    saves INTEGER,
    author_followers INTEGER,
    data_origin TEXT NOT NULL DEFAULT 'real' {_ORIGIN_CHECK},
    UNIQUE (project_id, platform, external_id)
);

CREATE TABLE IF NOT EXISTS contents (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,              -- post|comment|review|transcript|description|issue|answer|note
    text TEXT NOT NULL,
    lang TEXT,
    char_len INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    extraction_method TEXT NOT NULL, -- read_full|metadata_only|user_supplied|api_field
    collected_at TEXT NOT NULL,
    data_origin TEXT NOT NULL DEFAULT 'real' {_ORIGIN_CHECK},
    UNIQUE (project_id, content_hash)
);

CREATE TABLE IF NOT EXISTS pain_signals (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    content_id TEXT NOT NULL REFERENCES contents(id) ON DELETE CASCADE,
    quote TEXT NOT NULL,
    pain_type TEXT,
    segment TEXT,
    clarity REAL,                    -- 0..1 how explicit the problem statement is
    severity_claim TEXT,
    money_time_impact TEXT,
    current_workaround TEXT,
    wtp_signal TEXT,                 -- observed willingness-to-pay language, or NULL
    evidence_limits TEXT NOT NULL,
    verification_status TEXT NOT NULL DEFAULT 'unverified',
    extractor TEXT NOT NULL,         -- rules:v1 | llm:<model>
    signal_hash TEXT NOT NULL,
    duplicate_of TEXT REFERENCES pain_signals(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    data_origin TEXT NOT NULL DEFAULT 'real' {_ORIGIN_CHECK},
    UNIQUE (project_id, signal_hash)
);

CREATE TABLE IF NOT EXISTS clusters (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    label TEXT NOT NULL,
    problem_statement TEXT,
    audience TEXT,
    existing_solutions TEXT,
    impacts TEXT,
    knowledge_gaps TEXT,
    contradicting TEXT,
    distinct_sources INTEGER DEFAULT 0,
    distinct_authors INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    data_origin TEXT NOT NULL DEFAULT 'real' {_ORIGIN_CHECK}
);

CREATE TABLE IF NOT EXISTS cluster_members (
    cluster_id TEXT NOT NULL REFERENCES clusters(id) ON DELETE CASCADE,
    signal_id TEXT NOT NULL REFERENCES pain_signals(id) ON DELETE CASCADE,
    similarity REAL,
    PRIMARY KEY (cluster_id, signal_id)
);

CREATE TABLE IF NOT EXISTS competitors (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    url TEXT,
    pricing_text TEXT,
    pricing_evidence_url TEXT,
    features TEXT,
    complaints TEXT,
    gaps TEXT,
    source_id TEXT REFERENCES sources(id) ON DELETE SET NULL,
    mention_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    data_origin TEXT NOT NULL DEFAULT 'real' {_ORIGIN_CHECK},
    UNIQUE (project_id, name)
);

CREATE TABLE IF NOT EXISTS opportunities (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    cluster_id TEXT REFERENCES clusters(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    hypothesis TEXT,
    assumptions TEXT,                -- JSON list: unproven beliefs
    facts TEXT,                      -- JSON list: what evidence shows
    inferences TEXT,                 -- JSON list: model reasoning, not evidence
    evidence_strength REAL,
    attractiveness REAL,
    rubric_json TEXT,
    next_experiments TEXT,
    created_at TEXT NOT NULL,
    data_origin TEXT NOT NULL DEFAULT 'real' {_ORIGIN_CHECK}
);

CREATE TABLE IF NOT EXISTS human_tasks (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    run_id TEXT REFERENCES research_runs(id) ON DELETE SET NULL,
    kind TEXT NOT NULL,              -- login|manual_review|export|permission|decision|interview|weak_evidence
    title TEXT NOT NULL,
    what_is_needed TEXT NOT NULL,
    why_needed TEXT NOT NULL,
    steps TEXT NOT NULL,
    expected_return TEXT NOT NULL,
    after_completion TEXT NOT NULL,
    blocks_step TEXT,
    status TEXT NOT NULL DEFAULT 'open',   -- open|in_progress|completed|dismissed
    response_text TEXT,
    response_json TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS access_attempts (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
    run_id TEXT REFERENCES research_runs(id) ON DELETE SET NULL,
    platform TEXT NOT NULL,
    endpoint TEXT,
    status TEXT NOT NULL,            -- ok|denied|not_authorized|network_blocked|rate_limited|error
    http_code INTEGER,
    reason TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS exec_logs (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
    run_id TEXT REFERENCES research_runs(id) ON DELETE SET NULL,
    level TEXT NOT NULL,
    component TEXT NOT NULL,
    message TEXT NOT NULL,
    payload_json TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_contents_project ON contents(project_id, data_origin);
CREATE INDEX IF NOT EXISTS idx_signals_project ON pain_signals(project_id, data_origin);
CREATE INDEX IF NOT EXISTS idx_sources_project ON sources(project_id, data_origin);
CREATE INDEX IF NOT EXISTS idx_tasks_project ON human_tasks(project_id, status);
CREATE INDEX IF NOT EXISTS idx_steps_run ON run_steps(run_id, status);
"""

DEFAULT_DB = os.environ.get("ODA_DB", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "oda.sqlite3"))


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def connect(path: Optional[str] = None) -> sqlite3.Connection:
    path = path or DEFAULT_DB
    if path != ":memory:":
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Additive migrations for databases created by an earlier version."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(search_queries)")}
    if cols and "term" not in cols:
        conn.execute("ALTER TABLE search_queries ADD COLUMN term TEXT")
        conn.commit()

    scols = {r[1] for r in conn.execute("PRAGMA table_info(sources)")}
    if scols:
        for col in ("views", "likes", "comments_count", "shares", "saves",
                    "author_followers"):
            if col not in scols:
                conn.execute(f"ALTER TABLE sources ADD COLUMN {col} INTEGER")
        conn.commit()


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.execute(
        "INSERT INTO meta(key,value) VALUES('schema_version',?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()


def open_db(path: Optional[str] = None) -> sqlite3.Connection:
    conn = connect(path)
    init_db(conn)
    return conn


@contextmanager
def tx(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def jdump(obj: Any) -> Optional[str]:
    if obj is None:
        return None
    return json.dumps(obj, ensure_ascii=False)


def jload(s: Optional[str], default: Any = None) -> Any:
    if not s:
        return default
    try:
        return json.loads(s)
    except Exception:
        return default


def log(conn: sqlite3.Connection, level: str, component: str, message: str,
        project_id: Optional[str] = None, run_id: Optional[str] = None,
        payload: Any = None) -> None:
    conn.execute(
        "INSERT INTO exec_logs(id,project_id,run_id,level,component,message,payload_json,created_at)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (new_id("log"), project_id, run_id, level, component, message, jdump(payload), now()),
    )
    conn.commit()


def record_access(conn: sqlite3.Connection, platform: str, status: str,
                  project_id: Optional[str] = None, run_id: Optional[str] = None,
                  endpoint: Optional[str] = None, http_code: Optional[int] = None,
                  reason: Optional[str] = None) -> str:
    aid = new_id("acc")
    conn.execute(
        "INSERT INTO access_attempts(id,project_id,run_id,platform,endpoint,status,http_code,reason,created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?)",
        (aid, project_id, run_id, platform, endpoint, status, http_code, reason, now()),
    )
    conn.commit()
    return aid


def rows(conn: sqlite3.Connection, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
    return list(conn.execute(sql, tuple(params)).fetchall())


def one(conn: sqlite3.Connection, sql: str, params: Iterable[Any] = ()) -> Optional[sqlite3.Row]:
    return conn.execute(sql, tuple(params)).fetchone()
