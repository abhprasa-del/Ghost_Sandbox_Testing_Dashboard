-- Run ONCE on the existing ghost_dashboard database (PostgreSQL 9.5):
--   PGPASSWORD=... psql -h <db-host> -U ghost_dash -d ghost_dashboard -f view_update.sql
--   (use -h localhost only when running ON the database server itself; otherwise -h 198.18.69.10)
--
-- CREATE OR REPLACE VIEW on 9.5 requires the original columns to stay in the same
-- order/name/type; new columns may only be appended at the END. That is why the
-- first 16 columns below are identical to the original v_dashboard.
-- This version also groups by metadata_mode: one row per ticket + ALSI version + metadata mode
-- (latest run each), so a DEFAULT run is no longer hidden by a newer NON_DEFAULT run.
-- Safe to re-run: the output columns are unchanged, only the DISTINCT ON key differs.

CREATE OR REPLACE VIEW v_dashboard AS
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
