"""UI smoke test: the Streamlit app must execute every tab without exceptions."""
import os

import pytest

from oda import db, orchestrator, store

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "synthetic_pain.jsonl")


def test_app_renders_all_tabs_without_exception(tmp_path, monkeypatch):
    dbp = str(tmp_path / "ui.sqlite3")
    conn = db.open_db(dbp)
    pid = store.create_project(conn, name="ui test", domain="ecommerce inventory",
                               market="sa", languages="ar,en", notes="ecommerce")
    from oda.connectors import get
    res = get("manual").parse(open(FIXTURE, encoding="utf-8").read())
    store.ingest_result(conn, pid, "manual", res, data_origin=db.REAL)
    orchestrator.run_pipeline(conn, pid, platforms=[], sector="ecommerce",
                              sleep_between=0, probe=False)
    conn.close()

    monkeypatch.setenv("ODA_DB", dbp)
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert len(at.tabs) == 9
    labels = [s.value for s in at.subheader]
    for expected in ["Source feasibility audit", "Problem clusters and their evidence chain",
                     "Opportunity hypotheses", "Human review tasks", "Report"]:
        assert expected in labels
    # the real/synthetic badge must be visible somewhere
    texts = [e.value for e in at.caption if isinstance(e.value, str)]
    texts += [e.value for e in at.markdown if isinstance(e.value, str)]
    assert any("REAL DATA" in t for t in texts), "origin badge must be shown"


def test_app_renders_with_an_empty_database(tmp_path, monkeypatch):
    dbp = str(tmp_path / "empty.sqlite3")
    db.open_db(dbp).close()
    monkeypatch.setenv("ODA_DB", dbp)
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
