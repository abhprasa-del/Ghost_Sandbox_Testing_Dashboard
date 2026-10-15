import re
from pathlib import Path

import pytest

from app.jobnames import JOB_NAME_MAP, is_known_job, normalize_job_name
from app.parser import derive_outcome, parse_comment_html, parse_owner_field

FIXTURES = sorted((Path(__file__).parent / "fixtures").glob("real_*.html"))
KNOWN_STATUS = {"Completed", "RUNNING", "STARTING", "SKIPPED", "TIMEOUT", "UNSTABLE", "FAILURE"}


def load(name):
    return parse_comment_html((Path(__file__).parent / "fixtures" / name).read_text())


def test_fixtures_present():
    assert len(FIXTURES) >= 9


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.name)
def test_every_real_fixture_parses(path):
    r = parse_comment_html(path.read_text())
    assert re.fullmatch(r"GREL-\d+", r.ticket_key)
    assert r.title
    assert r.alsi_version in ("alsi22", "alsi24")
    assert r.metadata_mode in ("DEFAULT", "NON_DEFAULT")
    assert r.sandbox_build_no and r.sandbox_build_url and r.sandbox_status
    assert r.jobs
    names = [j.job_name for j in r.jobs]
    assert len(names) == len(set(names))
    for j in r.jobs:
        assert j.job_status in KNOWN_STATUS
        assert j.outcome in ("PASSED", "DEGRADED", "NO_INFO", "NA")
        assert is_known_job(j.job_name)
        if j.job_name.endswith(" build") and j.job_status == "Completed":
            assert j.artifacts and j.artifacts[0].download_url.startswith("http")
            assert j.artifacts[0].wget_command.startswith("wget")
        if j.job_name == "Baseline Regression":
            for s in j.suites:
                assert s.suite_name in ("SECURITY", "FREEFLOW", "ESSL")
                assert s.job_link


def test_not_selected_names_match_job_column_or_known():
    job_col, not_sel = set(), set()
    for p in FIXTURES:
        r = parse_comment_html(p.read_text())
        job_col |= {j.job_name for j in r.jobs}
        not_sel |= set(r.not_selected_jobs)
        raw = re.findall(r"\(Not selected:([^)]*)\)", p.read_text())
        for line in raw:
            for n in line.split(","):
                assert is_known_job(n), n
    assert not_sel
    for n in not_sel:
        assert n in job_col or is_known_job(n), n


def test_aliases_normalize():
    assert normalize_job_name("ASAN") == "ASAN build"
    assert normalize_job_name(" baseline ") == "Baseline Regression"
    assert normalize_job_name("Baseline   Regression") == "Baseline Regression"
    assert normalize_job_name("Mystery") == "Mystery"
    assert set(JOB_NAME_MAP.values()) >= {"PERF", "ASAN AURA", "LSAN AURA"}


def test_full_run_with_perf():
    r = load("real_14470555.html")
    assert (r.ticket_key, r.alsi_version, r.metadata_mode) == ("GREL-6321", "alsi22", "DEFAULT")
    assert r.title == "Hats fields unreported for TCP but reported for QUIC"
    assert r.sandbox_build_no == 2319 and r.sandbox_status == "Completed"
    assert r.ghost_version == "22.6.4.6321-f2fc23cb925c61b6724dbee806ba54e9"
    assert r.ghost_crashes_url.endswith("version=22.6.4.6321")
    by = {j.job_name: j for j in r.jobs}
    assert by["PERF"].outcome == "PASSED"
    assert by["PERF"].summary_url and by["PERF"].analysis_url
    assert by["LOAD"].plots_url
    assert [j.job_name for j in r.jobs][-1] == "Baseline Regression"
    assert by["ASAN build"].artifacts[0].artifact_type == "GhostAsan"
    assert by["LSAN build"].artifacts[0].artifact_type == "Lsan"
    assert by["TSAN build"].artifacts[0].artifact_type == "Tsan"
    assert by["ASAN build"].artifacts[0].wget_command.startswith("wget --no-check-certificate https://")
    assert by["Baseline Regression"].job_status == "UNSTABLE"
    suites = {s.suite_name: s for s in by["Baseline Regression"].suites}
    assert set(suites) == {"SECURITY", "FREEFLOW", "ESSL"}
    assert suites["FREEFLOW"].report_link is None and suites["FREEFLOW"].siam_link
    assert suites["SECURITY"].report_link and suites["SECURITY"].siam_link


def test_running_and_skipped():
    r = load("real_14490711.html")
    assert r.sandbox_status == "RUNNING"
    by = {j.job_name: j for j in r.jobs}
    assert by["BATS"].job_status == "RUNNING"
    assert by["ASAN AURA"].job_status == "SKIPPED"
    assert "skipped" in by["ASAN AURA"].result_text


def test_non_default_and_not_selected():
    r = load("real_14399901.html")
    assert r.metadata_mode == "NON_DEFAULT"
    assert r.not_selected_jobs == [
        "LOAD", "BATS", "ASAN build", "LSAN build", "TSAN build", "Baseline Regression"]
    assert [j.job_name for j in r.jobs] == ["PERF"]
    assert r.jobs[0].job_status == "FAILURE"
    assert r.ghost_version is None


def test_timeout_no_info():
    r = load("real_14399467.html")
    base = {j.job_name: j for j in r.jobs}["Baseline Regression"]
    assert base.job_status == "TIMEOUT" and base.outcome == "NO_INFO"
    assert r.alsi_version == "alsi24"


@pytest.mark.parametrize("name,expected", [
    ("real_14445144.html", ["ESSL", "FREEFLOW", "SECURITY"]),
    ("real_14445147.html", ["FREEFLOW", "ESSL", "SECURITY"]),
    ("real_14467383.html", ["SECURITY", "ESSL", "FREEFLOW"]),
    ("real_14470555.html", ["FREEFLOW", "SECURITY", "ESSL"]),
    ("real_14471797.html", ["ESSL", "SECURITY", "FREEFLOW"]),
    ("real_14490711.html", ["SECURITY", "FREEFLOW", "ESSL"]),
])
def test_baseline_suite_orderings(name, expected):
    base = {j.job_name: j for j in load(name).jobs}["Baseline Regression"]
    assert [s.suite_name for s in base.suites] == expected
    assert all(s.job_link and s.siam_link for s in base.suites)


def test_missing_metadata_heading_defaults_to_default():
    # real_derived_no_heading.html is DERIVED from real_14399901.html (a NON_DEFAULT comment)
    # with the "(Tests with ...)" heading removed; it is not an original Jira comment.
    assert load("real_14399901.html").metadata_mode == "NON_DEFAULT"
    assert load("real_derived_no_heading.html").metadata_mode == "DEFAULT"


def test_ghost_version_falls_back_to_load():
    html = (Path(__file__).parent / "fixtures" / "real_14470555.html").read_text()
    # derived in-memory: strip the version line from the PERF cell only
    perf_cell_version = "Ghost version: 22.6.4.6321-f2fc23cb925c61b6724dbee806ba54e9"
    first = html.index(perf_cell_version)
    mutated = html[:first] + html[first + len(perf_cell_version):]
    assert parse_comment_html(mutated).ghost_version == "22.6.4.6321-f2fc23cb925c61b6724dbee806ba54e9"
    mutated2 = mutated.replace(perf_cell_version, "")
    assert parse_comment_html(mutated2).ghost_version is None


@pytest.mark.parametrize("text,expected", [
    ("Perf test passed, Summary", "PASSED"),
    ("PERF TEST DETECTED DEGRADATIONS", "DEGRADED"),
    ("Perf test detected Degradations but earlier passed", "DEGRADED"),
    ("NO INFORMATION FOUND", "NO_INFO"),
    ("Not Available", "NA"),
    ("", "NA"),
    (None, "NA"),
    ("passed and No information found", "PASSED"),
])
def test_outcome_derivation(text, expected):
    assert derive_outcome(text) == expected


@pytest.mark.parametrize("value,expected", [
    ({"displayName": "Alice A", "name": "alice"}, "Alice A"),
    ({"name": "bob"}, "bob"),
    ({"displayName": "", "name": "bob"}, "bob"),
    (None, None),
    ([], None),
    ([{"displayName": "Alice"}, {"name": "bob"}, None], "Alice, bob"),
    (["x", "y"], "x, y"),
    ({}, None),
])
def test_owner_field(value, expected):
    assert parse_owner_field(value) == expected
