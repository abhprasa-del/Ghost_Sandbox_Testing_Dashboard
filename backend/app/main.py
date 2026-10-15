import hmac
from contextlib import asynccontextmanager
from datetime import date
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from sqlalchemy import Date, asc, cast, desc, func, select
from sqlalchemy.engine import Engine

from .config import Settings, get_settings
from .db import check_dashboard_view, get_engine
from .jobnames import CANONICAL_JOBS, JOB_NAME_MAP
from .parser import parse_bats_groups, parse_job_links
from .jenkins import fetch_started_by
from .models import (
    BaselineSuite, BuildArtifact, JobResult, SyncLog, TestRun, Ticket, v_dashboard,
)
from .queries import CATEGORIES, SORTABLE, build_runs_query, category_expr
from .sync import is_sync_running, notify_sync

DESCRIPTION = """
Ghost sandbox test results dashboard API.

**Date filters:** `date_from` / `date_to` apply to the `commented_at` of the row shown
(the latest run of that ticket + ALSI version + metadata mode), as a calendar date in
`DASHBOARD_TZ`. Older runs are visible in the ticket history (`/api/tickets/{key}`).

**Categories** (one per run): running, failed (any job FAILURE/TIMEOUT), degraded (any job
outcome DEGRADED or status UNSTABLE), passed (sandbox Completed, none of the above), other.
"""


def create_app(engine: Engine | None = None, settings: Settings | None = None,
               check_view: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings or get_settings()
        app.state.engine = engine or get_engine()
        if check_view:
            check_dashboard_view(app.state.engine)
        yield

    app = FastAPI(title="Ghost Sandbox Dashboard", description=DESCRIPTION, lifespan=lifespan,
                  docs_url="/api/docs", openapi_url="/api/openapi.json")

    def eng(request: Request) -> Engine:
        return request.app.state.engine

    def cfg(request: Request) -> Settings:
        return request.app.state.settings

    def rows(conn, stmt, **kw):
        return [dict(r._mapping) for r in conn.execute(stmt, kw or None)]

    # ---- runs ---------------------------------------------------------------------
    @app.get("/api/runs")
    def list_runs(
        engine: Engine = Depends(eng), s: Settings = Depends(cfg),
        ticket: str | None = Query(None, description="Partial, case-insensitive match on key and title"),
        assignee: str | None = None, sqa: str | None = None, devqa: str | None = None,
        alsi: str | None = None, metadata_mode: Literal["DEFAULT", "NON_DEFAULT"] | None = None,
        status: str | None = Query(None, description="Filters on sandbox_status only"),
        job: str | None = Query(None, description="Job name (aliases accepted), e.g. PERF"),
        job_status: str | None = Query(None, description="Status of `job`, e.g. TIMEOUT"),
        has_degraded: bool | None = Query(None, description="Any of perf/load/baseline outcome is DEGRADED"),
        date_from: date | None = Query(None, description="Date of latest run, in DASHBOARD_TZ"),
        date_to: date | None = Query(None, description="Date of latest run, in DASHBOARD_TZ"),
        sort_by: str = "commented_at", sort_dir: Literal["asc", "desc"] = "desc",
        page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=500),
    ):
        if sort_by not in SORTABLE:
            raise HTTPException(422, "sort_by must be one of: %s" % ", ".join(sorted(SORTABLE)))
        q, cat = build_runs_query(
            ticket=ticket, assignee=assignee, sqa=sqa, devqa=devqa, alsi=alsi,
            metadata_mode=metadata_mode, status=status, job=job, job_status=job_status,
            has_degraded=has_degraded, date_from=date_from, date_to=date_to,
            tz=s.dashboard_tz)
        col = cat if sort_by == "category" else v_dashboard.c[sort_by]
        order = (asc if sort_dir == "asc" else desc)(col).nulls_last()
        q = q.order_by(order, v_dashboard.c.run_id.desc())
        total_q = select(func.count()).select_from(q.order_by(None).subquery())
        with engine.connect() as conn:
            total = conn.execute(total_q).scalar_one()
            items = rows(conn, q.limit(page_size).offset((page - 1) * page_size))
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    def _order(name):
        return CANONICAL_JOBS.index(name) if name in CANONICAL_JOBS else len(CANONICAL_JOBS)

    @app.get("/api/runs/{run_id}")
    def run_detail(run_id: int, engine: Engine = Depends(eng), s: Settings = Depends(cfg)):
        with engine.connect() as conn:
            cat = category_expr(TestRun.run_id, TestRun.sandbox_status).label("category")
            run = conn.execute(
                select(TestRun, Ticket.title, Ticket.assignee, Ticket.sqa_owner,
                       Ticket.devqa_owner, Ticket.status.label("ticket_status"),
                       Ticket.jira_url, cat)
                .join(Ticket, Ticket.ticket_key == TestRun.ticket_key)
                .where(TestRun.run_id == run_id)).first()
            if run is None:
                raise HTTPException(404, "run not found")
            data = dict(run._mapping)
            raw_html = data.pop("raw_html", None)
            jobs = rows(conn, select(JobResult).where(JobResult.run_id == run_id))
            jids = [j["job_result_id"] for j in jobs]
            arts = rows(conn, select(BuildArtifact).where(BuildArtifact.job_result_id.in_(jids)))
            suites = rows(conn, select(BaselineSuite).where(BaselineSuite.job_result_id.in_(jids)))
        for j in jobs:
            j["build_artifacts"] = [a for a in arts if a["job_result_id"] == j["job_result_id"]]
            j["baseline_suites"] = [x for x in suites if x["job_result_id"] == j["job_result_id"]]
        for j in jobs:
            if j["job_name"] == "BATS":
                j["bats_groups"] = parse_bats_groups(raw_html) if raw_html else []
            elif j["job_name"] in ("ASAN AURA", "LSAN AURA"):
                j["result_links"] = parse_job_links(raw_html, j["job_name"]) if raw_html else []
        jobs.sort(key=lambda j: _order(j["job_name"]))
        data["job_results"] = jobs
        data["sandbox_started_by"] = fetch_started_by(data.get("sandbox_build_url"), s)
        return data

    @app.get("/api/tickets/{key}")
    def ticket_detail(key: str, engine: Engine = Depends(eng)):
        with engine.connect() as conn:
            t = conn.execute(select(Ticket).where(Ticket.ticket_key == key.upper())).first()
            if t is None:
                raise HTTPException(404, "ticket not found")
            cat = category_expr(TestRun.run_id, TestRun.sandbox_status).label("category")
            runs = rows(conn, select(
                TestRun.run_id, TestRun.alsi_version, TestRun.metadata_mode,
                TestRun.sandbox_build_no, TestRun.sandbox_build_url, TestRun.sandbox_status,
                TestRun.ghost_version, TestRun.commented_at, TestRun.comment_edited,
                TestRun.not_selected_jobs, cat)
                .where(TestRun.ticket_key == t.ticket_key)
                .order_by(TestRun.commented_at.desc(), TestRun.run_id.desc()))
            if runs:
                jobs = rows(conn, select(JobResult.run_id, JobResult.job_name,
                                         JobResult.job_status, JobResult.outcome)
                            .where(JobResult.run_id.in_([r["run_id"] for r in runs])))
                for r in runs:
                    r["jobs"] = sorted(
                        [{k: j[k] for k in ("job_name", "job_status", "outcome")}
                         for j in jobs if j["run_id"] == r["run_id"]],
                        key=lambda j: _order(j["job_name"]))
        return {"ticket": dict(t._mapping), "runs": runs}

    # ---- summary / filters / meta ---------------------------------------------------
    @app.get("/api/summary")
    def summary(engine: Engine = Depends(eng), s: Settings = Depends(cfg)):
        """Run counts from test_runs/job_results (not v_dashboard), by calendar day in DASHBOARD_TZ.

        `last_7_days` = today and the 6 previous calendar days. Every run is in exactly
        one category, so each block's categories sum to `total`.
        """
        cat = category_expr(TestRun.run_id, TestRun.sandbox_status)
        local_day = cast(func.timezone(s.dashboard_tz, TestRun.commented_at), Date)
        today = cast(func.timezone(s.dashboard_tz, func.now()), Date)

        def block(conn, days_back):
            res = conn.execute(
                select(cat.label("c"), func.count())
                .where(local_day >= today - days_back, local_day <= today)
                .group_by(cat)).all()
            out = {c: 0 for c in CATEGORIES}
            out.update({c: n for c, n in res})
            out["total"] = sum(out[c] for c in CATEGORIES)
            return out

        with engine.connect() as conn:
            return {"timezone": s.dashboard_tz, "today": block(conn, 0),
                    "last_7_days": block(conn, 6)}

    @app.get("/api/filters")
    def filters(engine: Engine = Depends(eng)):
        def distinct(col):
            return list(conn.execute(
                select(col).where(col.is_not(None), col != "").distinct().order_by(col)).scalars())
        with engine.connect() as conn:
            return {
                "assignees": distinct(Ticket.assignee),
                "sqa": distinct(Ticket.sqa_owner),
                "devqa": distinct(Ticket.devqa_owner),
                "alsi_versions": distinct(TestRun.alsi_version),
                "metadata_modes": ["DEFAULT", "NON_DEFAULT"],
                "statuses": distinct(TestRun.sandbox_status),
            }

    @app.get("/api/meta")
    def meta(s: Settings = Depends(cfg)):
        """Single source of truth for job-name normalization, used by the frontend."""
        return {"job_name_map": JOB_NAME_MAP, "canonical_jobs": CANONICAL_JOBS,
                "categories": CATEGORIES, "jira_base_url": s.jira_browse_url,
                "dashboard_tz": s.dashboard_tz}

    # ---- sync -----------------------------------------------------------------------
    @app.post("/api/sync", status_code=202)
    def trigger_sync(engine: Engine = Depends(eng), s: Settings = Depends(cfg),
                     x_sync_token: str | None = Header(None)):
        """Ask the sync worker to run now. Never runs the sync in this process."""
        if not s.sync_token or not x_sync_token or not hmac.compare_digest(
                x_sync_token.encode(), s.sync_token.encode()):
            raise HTTPException(401, "invalid or missing X-Sync-Token")
        if not notify_sync(engine):
            raise HTTPException(409, "a sync is already running")
        return {"status": "requested"}

    @app.get("/api/sync/status")
    def sync_status(engine: Engine = Depends(eng)):
        running = is_sync_running(engine)
        with engine.connect() as conn:
            last = conn.execute(select(SyncLog).order_by(SyncLog.sync_id.desc()).limit(1)).first()
        return {"running": running, "last_sync": dict(last._mapping) if last else None}

    return app


app = create_app()
