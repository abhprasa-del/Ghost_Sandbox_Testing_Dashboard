import pytest
from sqlalchemy import inspect, text

from app.db import REQUIRED_VIEW_COLUMNS, check_dashboard_view
from app.models import Base, v_dashboard

pytestmark = pytest.mark.db


def test_models_match_tables(test_engine):
    insp = inspect(test_engine)
    for table in Base.metadata.sorted_tables:
        if table.info.get("is_view"):
            continue
        db_cols = {c["name"] for c in insp.get_columns(table.name)}
        assert {c.name for c in table.columns} == db_cols, table.name


def test_view_columns_match_model_in_order(test_engine):
    with test_engine.connect() as c:
        cols = c.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='v_dashboard' ORDER BY ordinal_position")).scalars().all()
    assert cols == [c.name for c in v_dashboard.columns] == REQUIRED_VIEW_COLUMNS


def test_check_dashboard_view_ok(test_engine):
    check_dashboard_view(test_engine)


def test_check_dashboard_view_detects_missing(test_engine):
    with test_engine.begin() as c:
        c.execute(text("CREATE TEMP VIEW dummy AS SELECT 1"))
    # Simulate by checking a bogus requirement list against the real view
    import app.db as d
    orig = d.REQUIRED_VIEW_COLUMNS
    d.REQUIRED_VIEW_COLUMNS = orig + ["nope"]
    try:
        with pytest.raises(RuntimeError, match="nope"):
            d.check_dashboard_view(test_engine)
    finally:
        d.REQUIRED_VIEW_COLUMNS = orig


def test_view_selectable_via_model(clean_db):
    from sqlalchemy import select
    with clean_db.connect() as c:
        assert c.execute(select(v_dashboard)).all() == []
