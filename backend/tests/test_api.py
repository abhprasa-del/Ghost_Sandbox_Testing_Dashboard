from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import create_app
from app.sync import advisory_lock, store_comment
from helpers import comment, html, q

pytestmark = pytest.mark.db
IST = ZoneInfo("Asia/Kolkata")


def ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000%z")


def put(engine, settings, cid, name=None, created=None, body=None):
    c = comment(cid, name or "real_14470555.html", created=created)
    if body is not None:
        c["renderedBody"] = body
    store_comment(engine, settings, c)


@pytest.fixture()
def client(clean_db, settings):
    with TestClient(create_app(clean_db, settings)) as c:
        yield c


def keys(resp):
    return [(i["ticket_key"], i["alsi_version"], i["metadata_mode"]) for i in resp.json()["items"]]


@pytest.fixture()
def seeded(clean_db, settings):
    names = ["real_14399467.html", "real_14399644.html", "real_14399901.html",
             "real_14445144.html", "real_14445147.html", "real_14467383.html",
             "real_14470555.html", "real_14471797.html", "real_14490711.html",
             "real_derived_no_heading.html"]
    for i, n in enumerate(names):
        put(clean_db, settings, 100 + i, n, created="2026-10-1%d" % (i % 9 + 1) + "T10:00:00.000+0000")
    with clean_db.begin() as c:
        c.execute(text("UPDATE tickets SET assignee='Dev One', sqa_owner='Sqa A', devqa_owner='Dq X' "
                       "WHERE ticket_key='GREL-6321'"))
        c.execute(text("UPDATE tickets SET assignee='Dev Two' WHERE ticket_key='GREL-6162'"))
    return clean_db


def test_startup_check_and_empty(client):
    assert client.get("/api/runs").json() == {"items": [], "total": 0, "page": 1, "page_size": 50}


def test_same_ticket_alsi_default_and_non_default_are_two_rows(client, seeded):
    r = client.get("/api/runs", params={"ticket": "GREL-6237"})
    assert sorted(keys(r)) == [("GREL-6237", "alsi22", "DEFAULT"), ("GREL-6237", "alsi22", "NON_DEFAULT")]
    assert r.json()["total"] == 2


def test_latest_run_per_row_only(clean_db, settings, client):
    put(clean_db, settings, 1, created="2026-10-10T10:00:00.000+0000")
    put(clean_db, settings, 2, created="2026-10-11T10:00:00.000+0000")
    items = client.get("/api/runs").json()["items"]
    assert len(items) == 1 and items[0]["commented_at"].startswith("2026-10-11")


def test_view_exposes_build_and_outcome_columns(clean_db, settings):
    put(clean_db, settings, 1)
    with clean_db.connect() as c:
        r = c.execute(text("SELECT asan_status, lsan_status, tsan_status, perf_outcome, "
                           "load_outcome, baseline_outcome, have_baseline, ticket_status "
                           "FROM v_dashboard")).one()
    assert r[:6] == ("Completed", "Completed", "Completed", "PASSED", "NA", "NA")
    assert r[6] == "UNSTABLE"


def test_ticket_search_partial_case_insensitive_key_and_title(client, seeded):
    assert {k[0] for k in keys(client.get("/api/runs", params={"ticket": "grel-62"}))} >= {"GREL-6236", "GREL-6237"}
    assert {k[0] for k in keys(client.get("/api/runs", params={"ticket": "HATS fields"}))} == {"GREL-6321"}
    assert client.get("/api/runs", params={"ticket": "100%"}).json()["total"] == 0
    assert client.get("/api/runs", params={"ticket": "%"}).json()["total"] == 0


def test_owner_alsi_mode_status_filters(client, seeded):
    g = lambda **p: client.get("/api/runs", params=p).json()
    assert [i["ticket_key"] for i in g(assignee="Dev One")["items"]] == ["GREL-6321"]
    assert g(sqa="Sqa A")["total"] == 1 and g(devqa="Dq X")["total"] == 1
    assert g(assignee="Dev Two")["total"] == 2
    assert {i["alsi_version"] for i in g(alsi="alsi24")["items"]} == {"alsi24"}
    assert g(metadata_mode="NON_DEFAULT")["total"] == 1
    assert [i["ticket_key"] for i in g(status="RUNNING")["items"]] == ["GREL-6388"]
    assert g(status="running")["total"] == 1
    assert client.get("/api/runs", params={"metadata_mode": "bogus"}).status_code == 422


def test_job_and_job_status_filters(client, seeded):
    g = lambda **p: {i["ticket_key"] for i in client.get("/api/runs", params=p).json()["items"]}
    assert g(job="PERF", job_status="FAILURE") == {"GREL-6236", "GREL-6237"}
    assert g(job="ASAN", job_status="completed") >= {"GREL-6321", "GREL-6388"}
    assert g(job="ASAN AURA", job_status="SKIPPED") == {"GREL-6388"}
    assert g(job="Baseline Regression", job_status="TIMEOUT") == {"GREL-6236"}
    assert g(job_status="RUNNING") == {"GREL-6388"}


def test_has_degraded(clean_db, settings, client):
    put(clean_db, settings, 1)
    degraded = html("real_14470555.html").replace("Perf test passed", "Perf test detected Degradations")
    put(clean_db, settings, 2, "real_14445147.html", body=degraded.replace("GREL-6321", "GREL-7000"))
    r = client.get("/api/runs", params={"has_degraded": "true"}).json()
    assert [i["ticket_key"] for i in r["items"]] == ["GREL-7000"]
    assert r["items"][0]["perf_outcome"] == "DEGRADED"
    assert client.get("/api/runs").json()["total"] == 2


def test_date_filters_use_dashboard_timezone(clean_db, settings, client):
    # 20:00 UTC on the 12th is 01:30 IST on the 13th
    put(clean_db, settings, 1, created="2026-10-12T20:00:00.000+0000")
    g = lambda **p: client.get("/api/runs", params=p).json()["total"]
    assert g(date_from="2026-10-13", date_to="2026-10-13") == 1
    assert g(date_to="2026-10-12") == 0
    assert g(date_from="2026-10-14") == 0
    assert g(date_from="2026-10-12") == 1


def test_sort_and_pagination(client, seeded):
    r = client.get("/api/runs", params={"sort_by": "ticket_key", "sort_dir": "asc", "page_size": 3}).json()
    assert len(r["items"]) == 3 and r["total"] >= 9
    ks = [i["ticket_key"] for i in r["items"]]
    assert ks == sorted(ks)
    p2 = client.get("/api/runs", params={"sort_by": "ticket_key", "sort_dir": "asc", "page_size": 3, "page": 2}).json()
    assert not {i["run_id"] for i in r["items"]} & {i["run_id"] for i in p2["items"]}
    assert client.get("/api/runs", params={"sort_by": "raw_html"}).status_code == 422
    assert client.get("/api/runs", params={"sort_by": "category"}).status_code == 200


def test_run_detail_and_404(client, seeded):
    rid = client.get("/api/runs", params={"ticket": "GREL-6321"}).json()["items"][0]["run_id"]
    d = client.get("/api/runs/%d" % rid).json()
    assert "raw_html" not in d and d["category"] == "degraded"
    names = [j["job_name"] for j in d["job_results"]]
    assert names == ["PERF", "LOAD", "BATS", "ASAN build", "ASAN AURA", "LSAN build",
                     "LSAN AURA", "TSAN build", "Baseline Regression"]
    by = {j["job_name"]: j for j in d["job_results"]}
    assert by["ASAN build"]["build_artifacts"][0]["wget_command"].startswith("wget")
    assert {s["suite_name"] for s in by["Baseline Regression"]["baseline_suites"]} == {"SECURITY", "FREEFLOW", "ESSL"}
    assert client.get("/api/runs/999999").status_code == 404


def test_ticket_history_across_alsi_and_modes(client, seeded):
    d = client.get("/api/tickets/grel-6237").json()
    assert d["ticket"]["ticket_key"] == "GREL-6237"
    assert len(d["runs"]) == 2
    assert {r["metadata_mode"] for r in d["runs"]} == {"DEFAULT", "NON_DEFAULT"}
    assert d["runs"][0]["jobs"][0]["job_name"] == "PERF"
    d2 = client.get("/api/tickets/GREL-6236").json()
    assert {r["alsi_version"] for r in d2["runs"]} == {"alsi22", "alsi24"}
    assert client.get("/api/tickets/GREL-1").status_code == 404


def test_summary_counts_from_test_runs_and_sums_to_total(clean_db, settings, client):
    now = datetime.now(IST)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    just_after = ts(midnight + timedelta(seconds=1))
    just_before = ts(midnight - timedelta(seconds=1))
    old = ts(now - timedelta(days=30))
    three_days = ts(now - timedelta(days=3))
    fail_over_degraded = (html("real_14470555.html")
                          .replace("Perf test passed", "Perf test detected Degradations")
                          .replace("UNSTABLE", "TIMEOUT").replace("GREL-6321", "GREL-7001"))
    # today (IST): passed, degraded (UNSTABLE), failed (TIMEOUT beats degraded), running
    put(clean_db, settings, 1, "real_14445147.html", created=just_after)
    put(clean_db, settings, 2, "real_14470555.html", created=just_after)
    put(clean_db, settings, 3, "real_14470555.html", created=just_after, body=fail_over_degraded)
    put(clean_db, settings, 4, "real_14490711.html", created=just_after)
    # yesterday (IST) and older
    put(clean_db, settings, 5, "real_14399644.html", created=just_before)
    put(clean_db, settings, 6, "real_14399467.html", created=three_days)
    put(clean_db, settings, 7, "real_14471797.html", created=old)
    with clean_db.begin() as c:  # a run with no jobs and unknown sandbox status -> other
        c.execute(text(
            "INSERT INTO test_runs (ticket_key, jira_comment_id, metadata_mode, commented_at) "
            "VALUES ('GREL-6321', '999', 'DEFAULT', now())"))
    s = client.get("/api/summary").json()
    assert s["timezone"] == "Asia/Kolkata"
    t = s["today"]
    assert (t["passed"], t["degraded"], t["failed"], t["running"], t["other"]) == (1, 1, 1, 1, 1)
    assert t["total"] == 5 == sum(t[c] for c in ("passed", "degraded", "failed", "running", "other"))
    w = s["last_7_days"]
    assert w["total"] == 7 and w["failed"] == 3  # +yesterday FAILURE run, +3-day TIMEOUT run
    assert w["total"] == sum(w[c] for c in ("passed", "degraded", "failed", "running", "other"))
    assert q(clean_db, "SELECT count(*) FROM test_runs")[0][0] == 8  # old run excluded


def test_summary_counts_runs_hidden_from_dashboard_view(clean_db, settings, client):
    now = ts(datetime.now(IST))
    put(clean_db, settings, 1, created=now)
    put(clean_db, settings, 2, created=now)
    assert client.get("/api/runs").json()["total"] == 1
    assert client.get("/api/summary").json()["today"]["total"] == 2


def test_row_category_matches_summary_logic(client, seeded):
    cats = {i["ticket_key"] + i["alsi_version"]: i["category"] for i in
            client.get("/api/runs", params={"page_size": 100}).json()["items"]}
    assert cats["GREL-6388alsi22"] == "running"
    assert cats["GREL-6236alsi22"] == "failed"
    assert cats["GREL-6321alsi22"] == "degraded"
    assert cats["GREL-6162alsi24"] == "passed"


def test_filters_and_meta(client, seeded):
    f = client.get("/api/filters").json()
    assert "Dev One" in f["assignees"] and f["sqa"] == ["Sqa A"] and f["devqa"] == ["Dq X"]
    assert f["alsi_versions"] == ["alsi22", "alsi24"]
    m = client.get("/api/meta").json()
    assert m["job_name_map"]["asan"] == "ASAN build"
    assert "ASAN AURA" in m["canonical_jobs"]


def test_sync_endpoint_auth_202_409_and_status(clean_db, settings, client):
    assert client.post("/api/sync").status_code == 401
    assert client.post("/api/sync", headers={"X-Sync-Token": "wrong"}).status_code == 401
    ok = client.post("/api/sync", headers={"X-Sync-Token": "s"})
    assert ok.status_code == 202
    st = client.get("/api/sync/status").json()
    assert st == {"running": False, "last_sync": None}
    with advisory_lock(settings.database_url) as got:
        assert got
        assert client.post("/api/sync", headers={"X-Sync-Token": "s"}).status_code == 409
        assert client.get("/api/sync/status").json()["running"] is True
    with clean_db.begin() as c:
        c.execute(text("INSERT INTO sync_log (status, comments_seen, runs_upserted) VALUES ('SUCCESS', 3, 2)"))
    last = client.get("/api/sync/status").json()["last_sync"]
    assert last["status"] == "SUCCESS" and last["runs_upserted"] == 2


def test_sync_disabled_without_configured_token(clean_db, settings):
    from dataclasses import replace
    with TestClient(create_app(clean_db, replace(settings, sync_token=""))) as c:
        assert c.post("/api/sync", headers={"X-Sync-Token": ""}).status_code == 401
