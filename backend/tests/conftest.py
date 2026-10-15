import os
from pathlib import Path
from urllib.parse import urlparse

import pytest
from sqlalchemy import create_engine, text

PROD_HOST = "198.18.69.10"
FIXTURES = Path(__file__).parent / "fixtures"
DB_DIR = Path(__file__).resolve().parents[2] / "db"


def pytest_configure(config):
    config.addinivalue_line("markers", "db: needs a reachable test PostgreSQL (TEST_DATABASE_URL)")
    url = os.environ.get("TEST_DATABASE_URL")
    if url and urlparse(url.replace("+psycopg2", "")).hostname == PROD_HOST:
        pytest.exit("TEST_DATABASE_URL points at the production DB host; aborting.", returncode=2)


@pytest.fixture(scope="session")
def test_engine():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    if urlparse(url.replace("+psycopg2", "")).hostname == PROD_HOST:
        pytest.exit("refusing to run against production host", returncode=2)
    eng = create_engine(url, future=True)
    try:
        with eng.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        pytest.skip("test DB unreachable: %s" % exc)
    with eng.begin() as c:
        c.execute(text(
            "DO $$ BEGIN IF to_regclass('public.tickets') IS NULL THEN "
            "RAISE EXCEPTION 'schema not loaded'; END IF; END $$"
        ))
        c.execute(text((DB_DIR / "view_update.sql").read_text()))
    return eng


@pytest.fixture()
def clean_db(test_engine):
    with test_engine.begin() as c:
        c.execute(text("TRUNCATE tickets, sync_log RESTART IDENTITY CASCADE"))
    return test_engine


@pytest.fixture()
def settings(clean_db):
    from helpers import make_settings
    return make_settings()
