import threading
import time
from datetime import datetime, timedelta, timezone

import psycopg2
import pytest
from sqlalchemy import text

from app.config import Settings
from app.jira import JiraClient, parse_jira_time
from app.sync import (
    LOCK_CLASS, LOCK_OBJ, advisory_lock, is_sync_running, notify_sync, raw_dsn, run_sync,
)
from app.worker import Worker

from helpers import FakeJira, comment, q


pytestmark = pytest.mark.db


def test_upsert_idempotent_and_updates_ticket_timestamp(clean_db, settings):
    jira = FakeJira([comment(1, "real_14470555.html")])
    assert run_sync(clean_db, jira, settings)["upserted"] == 1
    counts = lambda: q(clean_db, "SELECT (SELECT count(*) FROM test_runs),"
                       "(SELECT count(*) FROM job_results),(SELECT count(*) FROM build_artifacts),"
                       "(SELECT count(*) FROM baseline_suites)")[0]
    first = counts()
    assert first == (1, 9, 3, 3)
    t1 = q(clean_db, "SELECT updated_at FROM tickets")[0][0]
    time.sleep(0.05)
    run_sync(clean_db, jira, settings)
    assert counts() == first
    assert q(clean_db, "SELECT updated_at FROM tickets")[0][0] > t1


def test_edited_comment_replaces_children(clean_db, settings):
    run_sync(clean_db, FakeJira([comment(1, "real_14399644.html")]), settings)
    assert q(clean_db, "SELECT count(*) FROM job_results")[0][0] == 9
    edited = comment(1, "real_14399901.html", updated="2099-01-01T00:00:00.000+0000")
    edited["created"] = comment(1, "real_14399644.html")["created"]
    run_sync(clean_db, FakeJira([edited]), settings)
    assert q(clean_db, "SELECT count(*) FROM test_runs")[0][0] == 1
    assert q(clean_db, "SELECT count(*) FROM job_results")[0][0] == 1
    assert q(clean_db, "SELECT count(*) FROM build_artifacts")[0][0] == 0
    assert q(clean_db, "SELECT comment_edited, metadata_mode FROM test_runs")[0] == (True, "NON_DEFAULT")


def test_bad_comment_does_not_abort(clean_db, settings):
    bad = comment(666, "real_14470555.html", created="not-a-date")
    res = run_sync(clean_db, FakeJira([bad, comment(2, "real_14470555.html")]), settings)
    assert res["upserted"] == 1 and res["status"] == "FAILED"
    assert q(clean_db, "SELECT count(*) FROM test_runs")[0][0] == 1
    status, err = q(clean_db, "SELECT status, error_message FROM sync_log")[0]
    assert status == "FAILED" and "666" in err


def test_success_log_and_author_filter(clean_db, settings):
    jira = FakeJira([comment(1, "real_14470555.html"), comment(2, "real_14399901.html", author="bob")])
    res = run_sync(clean_db, jira, settings)
    assert res["status"] == "SUCCESS"
    assert q(clean_db, "SELECT comments_seen, runs_upserted, status, error_message FROM sync_log")[0] \
        == (1, 1, "SUCCESS", None)


def test_deleted_comments_keep_runs(clean_db, settings):
    run_sync(clean_db, FakeJira([comment(1, "real_14470555.html")]), settings)
    run_sync(clean_db, FakeJira([]), settings)
    assert q(clean_db, "SELECT count(*) FROM test_runs")[0][0] == 1


def test_advisory_lock_skips_second_sync(clean_db, settings):
    with advisory_lock(settings.database_url) as got:
        assert got
        assert is_sync_running(clean_db)
        assert run_sync(clean_db, FakeJira([comment(1, "real_14470555.html")]), settings) is None
        assert notify_sync(clean_db) is False
    assert q(clean_db, "SELECT count(*) FROM sync_log")[0][0] == 0  # skip writes no log row
    assert not is_sync_running(clean_db)
    assert notify_sync(clean_db) is True


def test_status_query_uses_pg_locks(clean_db, settings):
    other = psycopg2.connect(raw_dsn(settings.database_url))
    other.autocommit = True
    cur = other.cursor()
    cur.execute("SELECT pg_try_advisory_lock(%s,%s)", (LOCK_CLASS, LOCK_OBJ))
    assert is_sync_running(clean_db)
    other.close()  # crash: lock disappears with the connection
    time.sleep(0.3)
    assert not is_sync_running(clean_db)


def test_lock_released_after_sync_and_not_pooled(clean_db, settings):
    run_sync(clean_db, FakeJira([]), settings)
    assert not is_sync_running(clean_db)
    assert clean_db.pool.checkedout() == 0


def test_owner_refresh_new_and_recent_only(clean_db, settings):
    old = (datetime.now(timezone.utc) - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%S.000+0000")
    issues = {
        "GREL-6321": {"fields": {
            "assignee": {"displayName": "Dev One", "name": "dev1"},
            "status": {"name": "In QA"},
            "customfield_1": [{"displayName": "Sqa A"}, {"name": "sqa_b"}],
            "customfield_2": None}},
    }
    jira = FakeJira([comment(1, "real_14470555.html"), comment(2, "real_14399644.html", created=old)], issues)
    run_sync(clean_db, jira, settings)
    # GREL-6236 is new in this sync, so it is fetched even though its run is old
    assert set(jira.fetched) == {"GREL-6321", "GREL-6236"}
    row = q(clean_db, "SELECT assignee, status, sqa_owner, devqa_owner FROM tickets WHERE ticket_key='GREL-6321'")[0]
    assert row == ("Dev One", "In QA", "Sqa A, sqa_b", None)
    # second sync: the 60-day-old ticket is no longer new nor recent
    jira.fetched.clear()
    run_sync(clean_db, jira, settings)
    assert set(jira.fetched) == {"GREL-6321"}


def test_owner_not_overwritten_by_title_upsert(clean_db, settings):
    issues = {"GREL-6321": {"fields": {"assignee": {"displayName": "Dev One"}}}}
    jira = FakeJira([comment(1, "real_14470555.html")], issues)
    run_sync(clean_db, jira, settings)
    jira2 = FakeJira([comment(1, "real_14470555.html")], issues)
    jira2.get_issue = lambda k: (_ for _ in ()).throw(RuntimeError("jira down"))
    res = run_sync(clean_db, jira2, settings)
    assert q(clean_db, "SELECT assignee FROM tickets")[0][0] == "Dev One"
    assert res["status"] == "FAILED"


def _wait(cond, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_notify_wakes_worker_and_burst_coalesces(clean_db, settings):
    calls = []

    def fake_sync():
        calls.append(1)
        time.sleep(0.2)

    w = Worker(settings.database_url, fake_sync, interval=3600)
    t = threading.Thread(target=w.run_forever, daemon=True)
    t.start()
    assert _wait(lambda: len(calls) == 1)  # startup sync
    time.sleep(0.6)  # notifications arriving during a sync are drained by design
    for _ in range(5):
        with clean_db.begin() as c:
            c.execute(text("SELECT pg_notify('ghost_sync','')"))
    assert _wait(lambda: len(calls) >= 2)
    time.sleep(0.8)
    assert len(calls) <= 3  # burst yields at most one extra sync
    w.stop.set()
    with clean_db.begin() as c:
        c.execute(text("SELECT pg_notify('ghost_sync','')"))
    t.join(5)
    assert not t.is_alive()


def test_worker_reconnects_after_connection_drop(clean_db, settings):
    calls = []
    w = Worker(settings.database_url, lambda: calls.append(1), interval=3600, reconnect_delay=0.2)
    t = threading.Thread(target=w.run_forever, daemon=True)
    t.start()
    assert _wait(lambda: len(calls) == 1)
    with clean_db.begin() as c:
        c.execute(text(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE query LIKE 'LISTEN%' AND pid <> pg_backend_pid()"))
    time.sleep(1.0)
    with clean_db.begin() as c:
        c.execute(text("SELECT pg_notify('ghost_sync','')"))
    assert _wait(lambda: len(calls) >= 2)
    w.stop.set()
    with clean_db.begin() as c:
        c.execute(text("SELECT pg_notify('ghost_sync','')"))
    t.join(5)


# -- Jira client (no DB) ---------------------------------------------------------------
class _Resp:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


class _Session:
    def __init__(self):
        self.headers = {}
        self.calls = []

    def get(self, url, params=None, verify=None, timeout=None):
        self.calls.append((url, params, verify))
        if url.endswith("/comment"):
            start = params["startAt"]
            return _Resp({"total": 5, "comments": [{"id": i} for i in range(start, min(start + 2, 5))]})
        return _Resp([{"id": "customfield_10", "name": "SQA"}, {"id": "customfield_11", "name": "DevQA"}])


def _jira_settings(**kw):
    base = dict(jira_base_url="https://j/jira", jira_browse_url="https://j/jira", jira_token="tok", jira_ssl_verify=True,
                jira_ca_bundle=None, jira_client_cert=None, jenkins_ca_bundle=None, jira_client_key=None, database_url="", source_ticket="GREL-799", sync_token="",
                dashboard_tz="Asia/Kolkata", owner_refresh_days=14, jira_field_sqa=None,
                jira_field_devqa=None)
    base.update(kw)
    return Settings(**base)


def test_jira_pagination_auth_and_verify():
    s = _Session()
    c = JiraClient(_jira_settings(), s)
    assert [x["id"] for x in c.iter_comments("GREL-799", page_size=2)] == [0, 1, 2, 3, 4]
    assert s.headers["Authorization"] == "Bearer tok"
    assert all(call[2] is True for call in s.calls)
    assert c.discover_owner_fields() == ("customfield_10", "customfield_11")


def test_jira_ca_bundle_overrides_verify_flag():
    s = _Session()
    JiraClient(_jira_settings(jira_ssl_verify=False, jira_ca_bundle="/certs/ca.pem"), s).get_issue("X-1")
    assert s.calls[0][2] == "/certs/ca.pem"
    assert _jira_settings().jira_verify is True


def test_parse_jira_time():
    assert parse_jira_time("2026-10-13T01:51:43.000+0530").utcoffset() == timedelta(hours=5, minutes=30)


class _CertSession(_Session):
    cert = None


def test_jira_client_certificate_for_mutual_tls():
    s = _CertSession()
    JiraClient(_jira_settings(jira_client_cert="/certs/c.pem", jira_client_key="/certs/k.pem"), s)
    assert s.cert == ("/certs/c.pem", "/certs/k.pem")
    s2 = _CertSession()
    JiraClient(_jira_settings(jira_client_cert="/certs/both.pem"), s2)
    assert s2.cert == "/certs/both.pem"
    s3 = _CertSession()
    JiraClient(_jira_settings(), s3)
    assert s3.cert is None


def test_jira_token_is_optional():
    s = _Session()
    JiraClient(_jira_settings(jira_token=""), s)
    assert "Authorization" not in s.headers


def test_non_run_comment_is_skipped_not_an_error(clean_db, settings):
    legacy = {"id": "5", "author": {"name": "_sae-test"}, "created": "2025-06-09T09:16:11.680+0000",
              "updated": "2025-06-09T09:16:11.680+0000",
              "renderedBody": "<table><tr><td>Triggered Sandbox-Testing job</td><td>SUCCESS</td></tr></table>"}
    res = run_sync(clean_db, FakeJira([legacy, comment(2, "real_14470555.html")]), settings)
    assert res["status"] == "SUCCESS" and res["upserted"] == 1 and res["non_run"] == 1
    assert q(clean_db, "SELECT comments_seen, runs_upserted, error_message FROM sync_log")[0] == (2, 1, None)


def test_old_unchanged_comments_are_not_rewritten(clean_db, settings):
    old = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%S.000+0000")
    jira = FakeJira([comment(1, "real_14470555.html", created=old)])
    assert run_sync(clean_db, jira, settings)["upserted"] == 1
    assert run_sync(clean_db, jira, settings)["upserted"] == 0  # unchanged and old
    changed = comment(1, "real_14470555.html", created=old)
    changed["renderedBody"] = changed["renderedBody"].replace("Perf test passed", "Perf test detected Degradations")
    assert run_sync(clean_db, FakeJira([changed]), settings)["upserted"] == 1
    assert q(clean_db, "SELECT outcome FROM job_results WHERE job_name='PERF'")[0][0] == "DEGRADED"


def test_recent_unchanged_comments_skipped_but_new_and_edited_are_written(clean_db, settings):
    issues = {"GREL-6321": {"fields": {"assignee": {"displayName": "Dev One"}}}}
    first = comment(1, "real_14470555.html")  # created now, i.e. inside the 14-day window
    jira = FakeJira([first], issues)
    assert run_sync(clean_db, jira, settings)["upserted"] == 1

    jira2 = FakeJira([first, comment(2, "real_14399901.html")], issues)
    res = run_sync(clean_db, jira2, settings)
    assert res["upserted"] == 1 and res["seen"] == 2  # only the new comment is written
    assert q(clean_db, "SELECT count(*) FROM test_runs")[0][0] == 2
    assert "GREL-6321" in jira2.fetched  # owners of recent tickets are still refreshed

    edited = dict(first, renderedBody=first["renderedBody"].replace("Perf test passed", "Perf test detected Degradations"))
    assert run_sync(clean_db, FakeJira([edited, comment(2, "real_14399901.html")], issues), settings)["upserted"] == 1
    assert q(clean_db, "SELECT outcome FROM job_results j JOIN test_runs r USING (run_id) "
                       "WHERE r.jira_comment_id='1' AND j.job_name='PERF'")[0][0] == "DEGRADED"


# -- retries and worker scheduling ---------------------------------------------------------
class _FlakySession(_Session):
    def __init__(self, failures, error=None, status=None):
        super().__init__()
        self.failures, self.error, self.status = failures, error, status

    def get(self, url, params=None, verify=None, timeout=None):
        self.calls.append(url)
        if len(self.calls) <= self.failures:
            if self.error:
                raise self.error
            resp = _Resp({})
            resp.status_code = self.status

            def boom():
                import requests
                raise requests.HTTPError("HTTP %s" % self.status, response=resp)
            resp.raise_for_status = boom
            return resp
        return _Resp({"ok": True})


def _client(session, attempts=4):
    return JiraClient(_jira_settings(), session, attempts=attempts, backoff=1.0, sleep=lambda s: slept.append(s))


slept: list = []


def test_jira_retries_dropped_connection_then_succeeds():
    import requests
    slept.clear()
    s = _FlakySession(2, error=requests.exceptions.SSLError("EOF occurred in violation of protocol"))
    assert _client(s).get_issue("GREL-1") == {"ok": True}
    assert len(s.calls) == 3 and slept == [1.0, 2.0]


def test_jira_gives_up_after_all_attempts():
    import requests
    slept.clear()
    s = _FlakySession(99, error=requests.exceptions.ConnectionError("refused"))
    with pytest.raises(requests.exceptions.ConnectionError):
        _client(s, attempts=3).get_issue("GREL-1")
    assert len(s.calls) == 3


def test_jira_retries_503_but_not_401():
    import requests
    slept.clear()
    s = _FlakySession(1, status=503)
    assert _client(s).get_issue("GREL-1") == {"ok": True} and len(s.calls) == 2
    s401 = _FlakySession(99, status=401)
    with pytest.raises(requests.HTTPError):
        _client(s401).get_issue("GREL-1")
    assert len(s401.calls) == 1  # authentication errors are not retried


def test_dropped_listener_during_sync_does_not_trigger_an_immediate_second_sync(clean_db, settings, monkeypatch):
    import app.worker as worker_mod
    import psycopg2
    real_drain = worker_mod.drain
    calls = []
    raised = []

    def flaky_drain(conn):
        # the first drain after the sync is where a dropped connection shows up in real life
        if calls and not raised:
            raised.append(1)
            raise psycopg2.OperationalError("SSL SYSCALL error: EOF detected")
        return real_drain(conn)

    monkeypatch.setattr(worker_mod, "drain", flaky_drain)
    w = Worker(settings.database_url, lambda: calls.append(1), interval=3600, reconnect_delay=0.2)
    t = threading.Thread(target=w.run_forever, daemon=True)
    t.start()
    assert _wait(lambda: raised)
    time.sleep(3)  # long enough for the reconnect; the old behaviour started the next sync here
    assert len(calls) == 1
    w.stop.set()
    with clean_db.begin() as c:
        c.execute(text("SELECT pg_notify('ghost_sync','')"))
    t.join(5)
