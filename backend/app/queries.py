"""Shared SQL pieces: run category logic and /api/runs filtering."""
from datetime import date

from sqlalchemy import Date, and_, case, cast, exists, func, or_, select

from .jobnames import normalize_job_name
from .models import JobResult, TestRun, v_dashboard

CATEGORIES = ["running", "failed", "degraded", "passed", "other"]


def category_expr(run_id_col, sandbox_status_col):
    """One category per run, precedence: running -> failed -> degraded -> passed -> other.

    running  = sandbox RUNNING or any job RUNNING/STARTING
    failed   = any job FAILURE or TIMEOUT
    degraded = any job outcome DEGRADED or any job status UNSTABLE
    passed   = none of the above and sandbox Completed
    """
    def any_job(*conds):
        return exists(select(JobResult.job_result_id).where(
            JobResult.run_id == run_id_col, or_(*conds)))

    status = func.upper(JobResult.job_status)
    running = or_(func.upper(sandbox_status_col) == "RUNNING",
                  any_job(status.in_(["RUNNING", "STARTING"])))
    failed = any_job(status.in_(["FAILURE", "TIMEOUT"]))
    degraded = any_job(func.upper(JobResult.outcome) == "DEGRADED", status == "UNSTABLE")
    return case(
        (running, "running"),
        (failed, "failed"),
        (degraded, "degraded"),
        (func.upper(sandbox_status_col) == "COMPLETED", "passed"),
        else_="other",
    )


def _like(term: str) -> str:
    esc = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return "%" + esc + "%"


SORTABLE = {c.name for c in v_dashboard.columns} | {"category"}


def build_runs_query(*, ticket=None, assignee=None, sqa=None, devqa=None, alsi=None,
                     metadata_mode=None, status=None, job=None, job_status=None,
                     has_degraded=None, date_from: date | None = None,
                     date_to: date | None = None, tz="Asia/Kolkata"):
    v = v_dashboard.c
    cat = category_expr(v.run_id, v.sandbox_status).label("category")
    q = select(v_dashboard, cat, TestRun.sandbox_build_url).select_from(
        v_dashboard.join(TestRun, TestRun.run_id == v_dashboard.c.run_id))
    conds = []
    if ticket:
        pat = _like(ticket.strip())
        conds.append(or_(v.ticket_key.ilike(pat, escape="\\"), v.title.ilike(pat, escape="\\")))
    for col, val in ((v.assignee, assignee), (v.sqa_owner, sqa), (v.devqa_owner, devqa),
                     (v.alsi_version, alsi), (v.metadata_mode, metadata_mode)):
        if val:
            conds.append(col == val)
    if status:
        conds.append(func.lower(v.sandbox_status) == status.lower())
    if job or job_status:
        jc = [JobResult.run_id == v.run_id]
        if job:
            jc.append(JobResult.job_name == normalize_job_name(job))
        if job_status:
            jc.append(func.lower(JobResult.job_status) == job_status.lower())
        conds.append(exists(select(JobResult.job_result_id).where(and_(*jc))))
    if has_degraded:
        conds.append(or_(v.perf_outcome == "DEGRADED", v.load_outcome == "DEGRADED",
                         v.baseline_outcome == "DEGRADED"))
    local_day = cast(func.timezone(tz, v.commented_at), Date)
    if date_from:
        conds.append(local_day >= date_from)
    if date_to:
        conds.append(local_day <= date_to)
    if conds:
        q = q.where(and_(*conds))
    return q, cat
