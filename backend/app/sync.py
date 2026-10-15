"""Jira -> DB sync. One locked run per call; never executed inside the API process."""
import hashlib
import logging
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import psycopg2
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Engine, make_url

from .config import Settings
from .models import BaselineSuite, BuildArtifact, JobResult, SyncLog, TestRun, Ticket
from .parser import NotARunComment, parse_comment_html, parse_owner_field
from .jira import parse_jira_time

log = logging.getLogger("ghost.sync")

LOCK_CLASS, LOCK_OBJ = 7990, 1
NOTIFY_CHANNEL = "ghost_sync"
AUTHOR = "_sae-test"

RUNNING_SQL = text(
    "SELECT 1 FROM pg_locks WHERE locktype='advisory' AND classid=:c AND objid=:o "
    "AND objsubid=2 AND database=(SELECT oid FROM pg_database WHERE datname=current_database())"
)


def is_sync_running(engine: Engine) -> bool:
    with engine.connect() as c:
        return c.execute(RUNNING_SQL, {"c": LOCK_CLASS, "o": LOCK_OBJ}).first() is not None


def notify_sync(engine: Engine) -> bool:
    """Ask the worker for a sync. False means a sync is already running (HTTP 409)."""
    if is_sync_running(engine):
        return False
    with engine.begin() as c:
        c.execute(text("SELECT pg_notify(:ch, '')"), {"ch": NOTIFY_CHANNEL})
    return True


def raw_dsn(database_url: str) -> str:
    url = make_url(database_url).set(drivername="postgresql")
    return url.render_as_string(hide_password=False)


def connect_listener(database_url: str):
    """Dedicated autocommit psycopg2 connection (outside the SQLAlchemy pool)."""
    conn = psycopg2.connect(
        raw_dsn(database_url), keepalives=1, keepalives_idle=60,
        keepalives_interval=10, keepalives_count=5,
    )
    conn.autocommit = True
    return conn


def _heartbeat(conn, stop: threading.Event, every: float = 30.0) -> None:
    """Keep the otherwise idle lock connection active so network devices do not drop it."""
    while not stop.wait(every):
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        except Exception:  # noqa: BLE001
            log.error("advisory-lock connection lost; lock no longer held")
            return


@contextmanager
def advisory_lock(database_url: str):
    """Yield True if the session-level lock was obtained, else False.

    The lock lives on its own connection for the whole sync; if the process dies the
    connection (and the lock) disappears with it.
    """
    conn = connect_listener(database_url)
    got = False
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s, %s)", (LOCK_CLASS, LOCK_OBJ))
            got = cur.fetchone()[0]
        stop = threading.Event()
        if got:
            threading.Thread(target=_heartbeat, args=(conn, stop), daemon=True).start()
        try:
            yield got
        finally:
            stop.set()
    finally:
        try:
            if got:
                with conn.cursor() as cur:
                    cur.execute("SELECT pg_advisory_unlock(%s, %s)", (LOCK_CLASS, LOCK_OBJ))
        finally:
            conn.close()


def _is_author(comment: dict) -> bool:
    a = comment.get("author") or {}
    return AUTHOR in (a.get("name"), a.get("key"), a.get("displayName"))


def store_comment(engine: Engine, settings: Settings, comment: dict) -> str:
    """Upsert one comment in its own transaction. Returns the ticket key."""
    html = comment.get("renderedBody") or comment.get("body") or ""
    parsed = parse_comment_html(html)
    commented_at = parse_jira_time(comment["created"])
    edited = comment.get("updated") != comment.get("created")
    with engine.begin() as conn:
        t = insert(Ticket).values(
            ticket_key=parsed.ticket_key,
            title=parsed.title,
            jira_url="%s/browse/%s" % (settings.jira_browse_url, parsed.ticket_key),
        )
        conn.execute(t.on_conflict_do_update(
            index_elements=[Ticket.ticket_key],
            set_={"title": t.excluded.title, "updated_at": func.now()},
        ))
        values = dict(
            ticket_key=parsed.ticket_key,
            jira_comment_id=str(comment["id"]),
            alsi_version=parsed.alsi_version,
            metadata_mode=parsed.metadata_mode,
            sandbox_build_no=parsed.sandbox_build_no,
            sandbox_build_url=parsed.sandbox_build_url,
            sandbox_status=parsed.sandbox_status,
            ghost_version=parsed.ghost_version,
            not_selected_jobs=parsed.not_selected_jobs,
            ghost_crashes_url=parsed.ghost_crashes_url,
            commented_at=commented_at,
            comment_edited=edited,
            raw_html=html,
        )
        r = insert(TestRun).values(**values)
        update_cols = {k: r.excluded[k] for k in values if k != "jira_comment_id"}
        update_cols["synced_at"] = func.now()
        run_id = conn.execute(
            r.on_conflict_do_update(index_elements=[TestRun.jira_comment_id], set_=update_cols)
            .returning(TestRun.run_id)
        ).scalar_one()
        conn.execute(delete(JobResult).where(JobResult.run_id == run_id))
        if parsed.jobs:
            ids = {
                name: jid
                for jid, name in conn.execute(
                    insert(JobResult).values([
                        dict(run_id=run_id, job_name=j.job_name, job_status=j.job_status,
                             outcome=j.outcome, result_text=j.result_text, job_url=j.job_url,
                             summary_url=j.summary_url, analysis_url=j.analysis_url,
                             plots_url=j.plots_url)
                        for j in parsed.jobs
                    ]).returning(JobResult.job_result_id, JobResult.job_name)
                )
            }
            arts = [dict(job_result_id=ids[j.job_name], artifact_type=a.artifact_type,
                         download_url=a.download_url, wget_command=a.wget_command)
                    for j in parsed.jobs for a in j.artifacts]
            suites = [dict(job_result_id=ids[j.job_name], suite_name=s.suite_name,
                           job_link=s.job_link, report_link=s.report_link, siam_link=s.siam_link)
                      for j in parsed.jobs for s in j.suites]
            if arts:
                conn.execute(insert(BuildArtifact).values(arts))
            if suites:
                conn.execute(insert(BaselineSuite).values(suites))
    return parsed.ticket_key


def _trunc(v: str | None, n: int) -> str | None:
    return v[:n] if v else v


def refresh_owners(engine: Engine, jira, settings: Settings, keys: set[str],
                   errors: list[str]) -> None:
    if not keys:
        return
    sqa_f, devqa_f = settings.jira_field_sqa, settings.jira_field_devqa
    if not (sqa_f and devqa_f):
        try:
            d_sqa, d_devqa = jira.discover_owner_fields()
            sqa_f, devqa_f = sqa_f or d_sqa, devqa_f or d_devqa
        except Exception as exc:  # noqa: BLE001
            errors.append("field discovery: %s" % exc)
    for key in sorted(keys):
        try:
            fields = jira.get_issue(key).get("fields", {})
            vals = {
                "assignee": _trunc(parse_owner_field(fields.get("assignee")), 100),
                "status": _trunc(parse_owner_field(fields.get("status")), 50),
                "updated_at": func.now(),
            }
            if sqa_f:
                vals["sqa_owner"] = _trunc(parse_owner_field(fields.get(sqa_f)), 100)
            if devqa_f:
                vals["devqa_owner"] = _trunc(parse_owner_field(fields.get(devqa_f)), 100)
            with engine.begin() as conn:
                conn.execute(update(Ticket).where(Ticket.ticket_key == key).values(**vals))
        except Exception as exc:  # noqa: BLE001
            errors.append("ticket %s owners: %s" % (key, exc))


def run_sync(engine: Engine, jira, settings: Settings) -> dict | None:
    """Run one sync under the advisory lock. Returns None if another sync holds it."""
    with advisory_lock(settings.database_url) as got:
        if not got:
            log.info("sync skipped: lock held elsewhere")
            return None
        return _sync_locked(engine, jira, settings)


def _sync_locked(engine: Engine, jira, settings: Settings) -> dict:
    with engine.begin() as conn:
        sync_id = conn.execute(
            insert(SyncLog).values(started_at=func.now()).returning(SyncLog.sync_id)
        ).scalar_one()
        existing = set(conn.execute(select(Ticket.ticket_key)).scalars())
        cutoff = datetime.now(timezone.utc) - timedelta(days=settings.owner_refresh_days)
        # Old runs whose comment text is unchanged are not rewritten (keeps big first syncs short).
        unchanged = {
            cid: digest for cid, digest in conn.execute(
                select(TestRun.jira_comment_id, func.md5(TestRun.raw_html))
                .where(TestRun.raw_html.is_not(None), TestRun.commented_at < cutoff))
        }
    errors: list[str] = []
    seen = upserted = skipped = 0
    touched: set[str] = set()
    try:
        for comment in jira.iter_comments(settings.source_ticket):
            if not _is_author(comment):
                continue
            seen += 1
            body = comment.get("renderedBody") or comment.get("body") or ""
            if unchanged.get(str(comment.get("id"))) == hashlib.md5(body.encode()).hexdigest():
                continue
            try:
                touched.add(store_comment(engine, settings, comment))
                upserted += 1
            except NotARunComment:
                skipped += 1
            except Exception as exc:  # noqa: BLE001
                log.warning("comment %s failed: %s", comment.get("id"), exc)
                errors.append("comment %s: %s" % (comment.get("id"), exc))
        with engine.connect() as conn:
            recent = set(conn.execute(
                select(TestRun.ticket_key).where(TestRun.commented_at >= cutoff).distinct()
            ).scalars())
        refresh_owners(engine, jira, settings, (touched - existing) | recent, errors)
    except Exception as exc:  # noqa: BLE001
        log.exception("sync failed")
        errors.append("sync: %s" % exc)
    status = "FAILED" if errors else "SUCCESS"
    with engine.begin() as conn:
        conn.execute(update(SyncLog).where(SyncLog.sync_id == sync_id).values(
            finished_at=func.now(), comments_seen=seen, runs_upserted=upserted,
            status=status, error_message="\n".join(errors) or None))
    log.info("sync %s: seen=%s upserted=%s non-run=%s errors=%s",
             sync_id, seen, upserted, skipped, len(errors))
    return {"sync_id": sync_id, "seen": seen, "upserted": upserted, "non_run": skipped,
            "status": status, "errors": errors}
