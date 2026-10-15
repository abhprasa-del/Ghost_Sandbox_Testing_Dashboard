-- Ghost Sandbox Test Dashboard - PostgreSQL schema
-- Source: comments posted by _sae-test on Jira ticket GREL-799

CREATE TABLE tickets (
    ticket_key      VARCHAR(20) PRIMARY KEY,          -- e.g. GREL-6388
    title           TEXT NOT NULL,
    status          VARCHAR(50),
    assignee        VARCHAR(100),                     -- developer
    sqa_owner       VARCHAR(100),                     -- assigned SQA
    devqa_owner     VARCHAR(100),                     -- assigned DevQA
    jira_url        TEXT,
    first_seen_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per Jira comment = one sandbox test run for one ticket + one ALSI version
CREATE TABLE test_runs (
    run_id              BIGSERIAL PRIMARY KEY,
    ticket_key          VARCHAR(20) NOT NULL REFERENCES tickets(ticket_key) ON DELETE CASCADE,
    jira_comment_id     VARCHAR(30) NOT NULL UNIQUE,   -- makes re-sync idempotent
    alsi_version        VARCHAR(20),                   -- alsi22 / alsi24
    metadata_mode       VARCHAR(30) NOT NULL DEFAULT 'DEFAULT',  -- DEFAULT | NON_DEFAULT
    sandbox_build_no    INT,                           -- Sandbox-Testing #2361
    sandbox_build_url   TEXT,
    sandbox_status      VARCHAR(20),                   -- RUNNING, Completed ...
    ghost_version       VARCHAR(100),
    not_selected_jobs   TEXT[],                        -- e.g. {LOAD,BATS}
    ghost_crashes_url   TEXT,
    commented_at        TIMESTAMPTZ NOT NULL,          -- time of Jira comment
    comment_edited      BOOLEAN DEFAULT FALSE,
    raw_html            TEXT,                          -- keep original for re-parsing
    synced_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_runs_ticket ON test_runs(ticket_key);
CREATE INDEX idx_runs_commented ON test_runs(commented_at DESC);
CREATE INDEX idx_runs_alsi ON test_runs(alsi_version);

-- Downstream jobs inside a run
CREATE TABLE job_results (
    job_result_id   BIGSERIAL PRIMARY KEY,
    run_id          BIGINT NOT NULL REFERENCES test_runs(run_id) ON DELETE CASCADE,
    job_name        VARCHAR(40) NOT NULL,   -- PERF, LOAD, BATS, ASAN build, ASAN AURA, LSAN build, LSAN AURA, TSAN build, Baseline Regression
    job_status      VARCHAR(20) NOT NULL,   -- Completed, RUNNING, STARTING, SKIPPED, TIMEOUT, UNSTABLE, FAILURE
    outcome         VARCHAR(20),            -- PASSED, DEGRADED, NO_INFO, NA (derived from result text)
    result_text     TEXT,                   -- e.g. "Perf test passed", "No information found"
    job_url         TEXT,
    summary_url     TEXT,
    analysis_url    TEXT,
    plots_url       TEXT,
    UNIQUE (run_id, job_name)
);
CREATE INDEX idx_jobs_status ON job_results(job_status);

-- Build download commands for ASAN / LSAN / TSAN
CREATE TABLE build_artifacts (
    artifact_id     BIGSERIAL PRIMARY KEY,
    job_result_id   BIGINT NOT NULL REFERENCES job_results(job_result_id) ON DELETE CASCADE,
    artifact_type   VARCHAR(20) NOT NULL,   -- GhostAsan, Lsan, Tsan
    download_url    TEXT NOT NULL,
    wget_command    TEXT
);

-- Baseline Regression sub-suites (SECURITY / FREEFLOW / ESSL)
CREATE TABLE baseline_suites (
    suite_id        BIGSERIAL PRIMARY KEY,
    job_result_id   BIGINT NOT NULL REFERENCES job_results(job_result_id) ON DELETE CASCADE,
    suite_name      VARCHAR(20) NOT NULL,
    job_link        TEXT,
    report_link     TEXT,
    siam_link       TEXT
);

-- Sync history / debugging
CREATE TABLE sync_log (
    sync_id         BIGSERIAL PRIMARY KEY,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    comments_seen   INT DEFAULT 0,
    runs_upserted   INT DEFAULT 0,
    status          VARCHAR(20),            -- SUCCESS | FAILED
    error_message   TEXT
);

-- Main dashboard view: one row per ticket + ALSI version + metadata mode, latest run
CREATE VIEW v_dashboard AS
SELECT DISTINCT ON (r.ticket_key, r.alsi_version, r.metadata_mode)
    -- original columns (do not reorder) ------------------------------------
    r.ticket_key, t.title, t.assignee, t.sqa_owner, t.devqa_owner,
    r.alsi_version, r.metadata_mode, r.sandbox_build_no, r.sandbox_status,
    r.ghost_version, r.commented_at, r.run_id,
    (SELECT job_status FROM job_results j WHERE j.run_id=r.run_id AND j.job_name='PERF')                AS have_perf,
    (SELECT job_status FROM job_results j WHERE j.run_id=r.run_id AND j.job_name='LOAD')                AS have_load,
    (SELECT job_status FROM job_results j WHERE j.run_id=r.run_id AND j.job_name='BATS')                AS have_bats,
    (SELECT job_status FROM job_results j WHERE j.run_id=r.run_id AND j.job_name='Baseline Regression') AS have_baseline,
    -- appended columns ----------------------------------------------------
    (SELECT job_status FROM job_results j WHERE j.run_id=r.run_id AND j.job_name='ASAN build')          AS asan_status,
    (SELECT job_status FROM job_results j WHERE j.run_id=r.run_id AND j.job_name='LSAN build')          AS lsan_status,
    (SELECT job_status FROM job_results j WHERE j.run_id=r.run_id AND j.job_name='TSAN build')          AS tsan_status,
    (SELECT outcome    FROM job_results j WHERE j.run_id=r.run_id AND j.job_name='PERF')                AS perf_outcome,
    (SELECT outcome    FROM job_results j WHERE j.run_id=r.run_id AND j.job_name='LOAD')                AS load_outcome,
    (SELECT outcome    FROM job_results j WHERE j.run_id=r.run_id AND j.job_name='Baseline Regression') AS baseline_outcome,
    r.not_selected_jobs,
    r.comment_edited,
    t.status AS ticket_status
FROM test_runs r JOIN tickets t USING (ticket_key)
ORDER BY r.ticket_key, r.alsi_version, r.metadata_mode, r.commented_at DESC;
