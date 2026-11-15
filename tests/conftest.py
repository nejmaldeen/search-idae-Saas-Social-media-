import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from oda import db  # noqa: E402

# Credentials that may be present in the developer's shell. Offline tests must
# never pick them up: an ambient token turns a "no credentials" assertion into
# a real, billable network call.
_AMBIENT_CREDS = (
    "APIFY_TOKEN", "YOUTUBE_API_KEY", "SCRAPECREATORS_KEY", "GITHUB_API_TOKEN",
    "REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "X_BEARER_TOKEN",
    "TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "IG_ACCESS_TOKEN",
    "IG_BUSINESS_ACCOUNT_ID", "G2_PARTNER_TOKEN", "CAPTERRA_TOKEN",
    "STACKEXCHANGE_KEY",
)


@pytest.fixture(autouse=True)
def _isolate_credentials(request, monkeypatch):
    """Strip ambient credentials from every test except those marked `network`."""
    if request.node.get_closest_marker("network"):
        return
    for name in _AMBIENT_CREDS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture()
def conn(tmp_path):
    c = db.open_db(str(tmp_path / "t.sqlite3"))
    yield c
    c.close()


@pytest.fixture()
def project(conn):
    from oda.store import create_project
    return create_project(conn, name="test", domain="ecommerce inventory", market="sa",
                          languages="ar,en", notes="ecommerce")
