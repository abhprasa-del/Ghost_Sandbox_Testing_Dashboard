from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from .config import get_settings

# Columns the API depends on, in view order.
REQUIRED_VIEW_COLUMNS = [
    "ticket_key", "title", "assignee", "sqa_owner", "devqa_owner",
    "alsi_version", "metadata_mode", "sandbox_build_no", "sandbox_status",
    "ghost_version", "commented_at", "run_id",
    "have_perf", "have_load", "have_bats", "have_baseline",
    "asan_status", "lsan_status", "tsan_status",
    "perf_outcome", "load_outcome", "baseline_outcome",
    "not_selected_jobs", "comment_edited", "ticket_status",
]

_engine: Engine | None = None


def make_engine(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True, future=True)


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = make_engine(get_settings().database_url)
    return _engine


def check_dashboard_view(engine: Engine) -> None:
    """Fail fast if v_dashboard is missing columns (view_update.sql not applied)."""
    with engine.connect() as c:
        rows = c.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'v_dashboard' AND table_schema = current_schema()"
            )
        ).scalars().all()
    missing = [col for col in REQUIRED_VIEW_COLUMNS if col not in rows]
    if missing:
        raise RuntimeError(
            "v_dashboard is missing columns: %s. Apply db/view_update.sql." % ", ".join(missing)
        )
