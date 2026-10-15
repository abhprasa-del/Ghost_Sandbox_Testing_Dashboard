from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import create_app
from app.parser import parse_bats_groups, parse_job_links
from app.sync import store_comment
from helpers import comment

FIX = Path(__file__).parent / "fixtures"


def groups(name):
    return parse_bats_groups((FIX / name).read_text())


def test_bats_groups_from_real_fixture():
    g = groups("real_14470555.html")
    assert [x["name"] for x in g] == [
        "group-common-1", "group-common-2", "group-common-3", "group-ff",
        "group-essl", "group-il", "group-security", "group-rdc"]
    first = g[0]
    assert first["name_url"].startswith("http://ffdevtest.engr.akamai.com:8080/bats/regular/query?runid=")
    assert [l["label"] for l in first["links"]] == ["Analysis"]
    assert first["links"][0]["url"].startswith("http://bats-ara.engr.akamai.com/main/bats_disp_runid?")
    assert first["note"] is None


def test_bats_group_with_text_only_result_and_linked_failure():
    plain = {x["name"]: x for x in groups("real_14467383.html")}["group-common-1"]
    assert plain["links"] == [] and plain["note"] == "No results found"
    failed = {x["name"]: x for x in groups("real_14399467.html")}["group-common-1"]
    assert failed["name_url"] is None
    assert failed["links"][0]["label"] == "Gigas/setup failed"


@pytest.mark.parametrize("name", ["real_14445147.html", "real_14490711.html", "real_14399901.html"])
def test_no_bats_groups_returns_empty(name):
    assert groups(name) == []


@pytest.mark.db
def test_api_sandbox_build_url_and_bats_groups(clean_db, settings):
    store_comment(clean_db, settings, comment(1, "real_14470555.html"))
    store_comment(clean_db, settings, comment(2, "real_14399644.html"))
    with TestClient(create_app(clean_db, settings)) as c:
        items = {i["ticket_key"]: i for i in c.get("/api/runs").json()["items"]}
        assert items["GREL-6321"]["sandbox_build_url"].endswith("/Sandbox-Testing/2319/")
        assert items["GREL-6321"]["sandbox_build_no"] == 2319
        with clean_db.begin() as conn:
            conn.execute(text("UPDATE test_runs SET sandbox_build_url = NULL WHERE ticket_key='GREL-6236'"))
        items = {i["ticket_key"]: i for i in c.get("/api/runs").json()["items"]}
        assert items["GREL-6236"]["sandbox_build_url"] is None
        assert items["GREL-6236"]["sandbox_build_no"] == 2238
        rid = items["GREL-6321"]["run_id"]
        jobs = {j["job_name"]: j for j in c.get("/api/runs/%d" % rid).json()["job_results"]}
        assert len(jobs["BATS"]["bats_groups"]) == 8
        assert jobs["BATS"]["outcome"] == "NA"
        assert "bats_groups" not in jobs["PERF"]


def test_aura_job_links_from_real_fixture():
    html = (FIX / "real_14470555.html").read_text()
    asan = parse_job_links(html, "ASAN AURA")
    assert [l["label"] for l in asan] == ["BATS Dashboard", "ASAN Dashboard", "AURA Recommended Tests"]
    assert all(l["url"].startswith("http") for l in asan)
    lsan = parse_job_links(html, "LSAN AURA")
    assert [l["label"] for l in lsan] == ["BATS Dashboard", "LSAN Dashboard", "AURA Recommended Tests"]


def test_aura_job_without_links_returns_empty():
    html = (FIX / "real_14490711.html").read_text()  # AURA jobs SKIPPED: text only
    assert parse_job_links(html, "ASAN AURA") == []
    assert parse_job_links(html, "NOPE") == []


@pytest.mark.db
def test_api_returns_result_links_for_aura_jobs_only(clean_db, settings):
    store_comment(clean_db, settings, comment(1, "real_14470555.html"))
    with TestClient(create_app(clean_db, settings)) as c:
        rid = c.get("/api/runs").json()["items"][0]["run_id"]
        jobs = {j["job_name"]: j for j in c.get("/api/runs/%d" % rid).json()["job_results"]}
    assert len(jobs["ASAN AURA"]["result_links"]) == 3
    assert len(jobs["LSAN AURA"]["result_links"]) == 3
    assert "result_links" not in jobs["PERF"] and "result_links" not in jobs["ASAN build"]


# -- "Started by user" (read from the Jenkins build API) ---------------------------------
from app import jenkins  # noqa: E402

REAL_CAUSES = {"actions": [
    {"_class": "hudson.model.CauseAction", "causes": [
        {"_class": "BuildUpstreamCause", "shortDescription": "Started by upstream project"},
        {"_class": "hudson.model.Cause$UserIdCause", "userName": "Sai Rama Krishna Reddy Adidela"},
        {"_class": "RebuildCause", "shortDescription": "Rebuilds build #2,365"}]},
    {"_class": "hudson.model.ParametersAction"}]}


class _Resp:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


class _Sess:
    def __init__(self, data=None, boom=False):
        self.data, self.boom, self.calls = data, boom, []

    def get(self, url, timeout=None, verify=None):
        self.calls.append(url)
        if self.boom:
            raise RuntimeError("unreachable")
        return _Resp(self.data)


@pytest.fixture(autouse=False)
def fresh_cache():
    jenkins._FOUND.clear()
    jenkins._FAILED.clear()


def _settings():
    from app.config import Settings
    return Settings(
        jira_base_url="https://j/jira", jira_browse_url="https://j/jira", jira_token="",
        jira_ssl_verify=True, jira_ca_bundle=None, jira_client_cert=None, jenkins_ca_bundle=None,
        jira_client_key=None, database_url="", source_ticket="GREL-799", sync_token="",
        dashboard_tz="Asia/Kolkata", owner_refresh_days=14, jira_field_sqa=None, jira_field_devqa=None)


def test_started_by_user_from_build_api(fresh_cache):
    s = _Sess(REAL_CAUSES)
    url = "https://ghost-test-cc.engr.akamai.com/jenkins/job/Sandbox-Testing/2367/"
    assert jenkins.fetch_started_by(url, _settings(), s) == "Sai Rama Krishna Reddy Adidela"
    assert s.calls == [url.rstrip("/") + "/api/json?tree=actions[causes[userName]]"]
    assert jenkins.fetch_started_by(url, _settings(), _Sess(boom=True)) == "Sai Rama Krishna Reddy Adidela"  # cached


def test_started_by_none_when_no_user_cause_or_unreachable_or_bad_url(fresh_cache):
    url = "https://ghost-test-cc.engr.akamai.com/jenkins/job/Sandbox-Testing/9/"
    assert jenkins.fetch_started_by(url, _settings(), _Sess({"actions": [{"causes": [{"shortDescription": "Started by timer"}]}]})) is None
    assert jenkins.fetch_started_by(url.replace("/9/", "/10/"), _settings(), _Sess(boom=True)) is None
    assert jenkins.fetch_started_by(None, _settings(), _Sess(REAL_CAUSES)) is None
    assert jenkins.fetch_started_by("ftp://x/job/1/", _settings(), _Sess(REAL_CAUSES)) is None
    assert jenkins.fetch_started_by("https://x/other/1/", _settings(), _Sess(REAL_CAUSES)) is None


@pytest.mark.db
def test_api_run_detail_includes_started_by(clean_db, settings, monkeypatch):
    store_comment(clean_db, settings, comment(1, "real_14470555.html"))
    monkeypatch.setattr("app.main.fetch_started_by", lambda url, s: "Some User" if url else None)
    with TestClient(create_app(clean_db, settings)) as c:
        rid = c.get("/api/runs").json()["items"][0]["run_id"]
        assert c.get("/api/runs/%d" % rid).json()["sandbox_started_by"] == "Some User"
