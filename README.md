# Ghost Sandbox Test Results Dashboard

Shows the sandbox test results that `_sae-test` posts as comments on Jira **GREL-799**, so developers,
DevQA and SQA can find their ticket without opening Jira.

```
Jira ──(sync service, every 15 min / on demand)──> PostgreSQL 9.5 (external) <── api (FastAPI) <── web (nginx + React)
```

| Service | What it does |
|---|---|
| `api` | FastAPI, read-only data API plus `POST /api/sync` (only sends a `NOTIFY`) |
| `sync` | The only process that talks to Jira. Syncs every 15 min and whenever it gets `NOTIFY ghost_sync` |
| `web` | nginx serving the React app and proxying `/api` to `api` (single origin, no CORS) |

## How the data flows

**Source:** a Jenkins job (`Sandbox-Testing`) posts one comment per sandbox run on Jira ticket **GREL-799**, as user
`_sae-test`. Each comment is an HTML table: the sandbox build, then the downstream jobs
(PERF, LOAD, BATS, ASAN/LSAN/TSAN builds and AURA jobs, Baseline Regression) with their status and result links.
These comments are the only data source; nothing is entered by hand.

```
 Jenkins "Sandbox-Testing"
        │ posts / updates a comment as _sae-test
        ▼
 Jira  GREL-799 comments
        │ 1. sync service reads them via REST (track-api host, client certificate)
        ▼
 sync (worker) ── parser (BeautifulSoup) ──► ticket, ALSI, mode, jobs, links, wget commands
        │ 2. upsert, one transaction per comment
        ▼
 PostgreSQL  tickets · test_runs · job_results · build_artifacts · baseline_suites · sync_log
        │ 3. v_dashboard = latest run per ticket + ALSI + metadata mode
        ▼
 api (FastAPI)  /api/runs · /api/runs/{id} · /api/tickets/{key} · /api/summary · /api/filters
        │ 4. nginx proxies /api (same origin)
        ▼
 web (React)  summary cards · table · detail dialog · history
```

1. **Sync.** Every 15 minutes (and on `POST /api/sync`) the `sync` service fetches all comments on GREL-799 and keeps
   those by `_sae-test`. Comments that are not run reports (the older 2025 format with no GREL link) are skipped.
   Comments older than `OWNER_REFRESH_DAYS` whose text is unchanged are not rewritten; recent or edited ones are.
2. **Parse and store.** Each comment becomes one `test_runs` row (ticket, ALSI version, DEFAULT/NON_DEFAULT mode,
   sandbox build number and URL, Ghost version, "not selected" jobs, crashes link, original `raw_html`) and its child rows:
   `job_results` (status, derived outcome PASSED/DEGRADED/NO_INFO/NA, result text, Summary/Analysis/Plots links),
   `build_artifacts` (wget commands) and `baseline_suites` (SECURITY/FREEFLOW/ESSL links). Ticket title comes from the
   comment; assignee, status, SQA and DevQA come from the Jira issue itself, refreshed for new tickets and for tickets
   with a run in the last `OWNER_REFRESH_DAYS` days. A sync never deletes runs.
3. **Read.** The API reads the `v_dashboard` view for the main table (one row per ticket + ALSI + mode, the latest
   run), and reads the base tables for detail, ticket history and the summary counts.
4. **Show.**
   * *Summary cards*: Today / Last 7 days, counted per run from `test_runs`/`job_results` in `DASHBOARD_TZ`.
     Each run is exactly one of: running, failed (any job FAILURE/TIMEOUT), degraded (a DEGRADED outcome or UNSTABLE),
     passed, other.
   * *Main table*: one row per ticket + ALSI + mode with colour badges per job, sandbox build link and last update.
     Filters and sort are kept in the URL; CSV export covers the current filters.
   * *Detail dialog* (click a row): all jobs including AURA, links, BATS groups, copyable wget commands,
     baseline suites, "not selected" jobs, ghost crashes link, and a history tab with earlier runs of the ticket.
   * *Header*: "Last synced X min ago" from `GET /api/sync/status`.

Because Jira is the source of truth, the database can always be rebuilt by applying `db/schema.sql` and running one
sync (see Backups for what a rebuild would lose).

The database is **external** (`198.18.69.10`). No migrations and no DB container for the app.

## 1. Database setup (once)

```bash
# new database
PGPASSWORD=... psql -h 198.18.69.10 -U ghost_dash -d ghost_dashboard -f db/schema.sql
# already-created database: only update the view
PGPASSWORD=... psql -h 198.18.69.10 -U ghost_dash -d ghost_dashboard -f db/view_update.sql
```

Use `-h localhost` only when running on the DB server itself. `schema.sql` already contains the extended view;
re-running `view_update.sql` is harmless. The API refuses to start if `v_dashboard` lacks the expected columns.

On the DB server, `pg_hba.conf` must allow the Docker host or subnet (PostgreSQL 9.5 uses `md5`):

```
host  ghost_dashboard  ghost_dash  <docker-host-or-subnet>  md5
```

Also check `listen_addresses` in `postgresql.conf` and that the firewall allows TCP 5432.
Inside containers always use the server IP, never `localhost`.

> **PostgreSQL 9.5 is end-of-life.** SQLAlchemy 2.x does not officially support it, so the code sticks to plain
> `select/insert/update/delete` and `ON CONFLICT`. Upgrading PostgreSQL is recommended.

## 2. Configure and run

To run it on a server instead of your workstation, follow [DEPLOY.md](DEPLOY.md).

```bash
cp .env.example .env     # fill in JIRA_TOKEN, DATABASE_URL password, SYNC_TOKEN
docker compose up -d --build
```

Open **http://localhost:8080** (or `http://<docker-host>:8080`).

* Jira TLS: set `JIRA_CA_BUNDLE=/certs/ca.pem` and put the PEM file in `./certs` (mounted read-only into `sync`).
  If unset, `JIRA_SSL_VERIFY` is used. Verification is never disabled by default.
  If Jira rejects the connection with `certificate required`, it needs a client certificate: put it in `./certs` and
  set `JIRA_CLIENT_CERT` (and `JIRA_CLIENT_KEY` if the key is in a separate file).
* SQA/DevQA: set `JIRA_FIELD_SQA` / `JIRA_FIELD_DEVQA` (e.g. `customfield_12345`), otherwise the sync looks the
  fields up by name via `/rest/api/2/field`.

### First sync

The sync service runs one sync at startup. To trigger another one (admins only):

```bash
curl -X POST -H "X-Sync-Token: $SYNC_TOKEN" http://localhost:8080/api/sync   # 202 requested, 409 already running, 401 bad token
curl http://localhost:8080/api/sync/status                                    # {running, last_sync}
docker compose logs -f sync
```

There is deliberately **no sync button in the UI**: `VITE_*` variables are compiled into the JavaScript bundle, so
`SYNC_TOKEN` must never reach the frontend. If a button is wanted later, a reverse proxy must add the header server-side.

### How the sync works

* One run = one `pg_try_advisory_lock(7990, 1)` held on a dedicated connection; a second sync is skipped
  (no `sync_log` row) or reported as busy (API returns 409). "Running" is read from `pg_locks`.
* Each Jira comment is upserted in its own transaction; a bad comment is logged in `sync_log.error_message` and the
  rest continue. `sync_log.status` is `SUCCESS` only if there were no errors, otherwise `FAILED`.
* Deleted Jira comments are never removed from the database.
* Ticket owners/status are refreshed for new tickets and for every ticket with a run in the last
  `OWNER_REFRESH_DAYS` days.

## 3. API

Interactive docs at `/api/docs` (e.g. http://localhost:8080/api/docs).

| Endpoint | Notes |
|---|---|
| `GET /api/runs` | One row per ticket + ALSI + metadata mode (latest run). Filters: `ticket, assignee, sqa, devqa, alsi, metadata_mode, status, job, job_status, has_degraded, date_from, date_to`; `sort_by, sort_dir, page, page_size`. `date_*` apply to the date of the **latest run** in `DASHBOARD_TZ`. |
| `GET /api/runs/{id}` | Full detail incl. jobs, build artifacts, baseline suites |
| `GET /api/tickets/{key}` | Ticket and all its runs (every ALSI version and mode) |
| `GET /api/summary` | Counts for today and the last 7 days from `test_runs`/`job_results` |
| `GET /api/filters`, `GET /api/meta` | Filter values; job-name mapping, canonical jobs |
| `POST /api/sync`, `GET /api/sync/status` | See above |

Categories (one per run, precedence running → failed → degraded → passed → other): **failed** = any job
FAILURE/TIMEOUT; **degraded** = any job outcome DEGRADED or status UNSTABLE; **running** = sandbox RUNNING or any job
RUNNING/STARTING; **passed** = sandbox Completed and none of the above.

## 4. Backups (optional, weekly)

Everything in the database is derived from Jira, so it can be rebuilt (apply `db/schema.sql`, run one sync). A backup
saves the long first sync and keeps runs whose Jira comments were later deleted (the app never deletes runs).
Ask the DB admins whether the PostgreSQL instance is already backed up; if so, this is redundant.

[`scripts/backup.sh`](scripts/backup.sh) writes a compressed `pg_dump` and keeps the last 8 weeks
(`KEEP_DAYS`, `BACKUP_DIR`, `DB_HOST`, `DB_NAME`, `DB_USER` can be overridden through the environment).

```bash
# once, on the machine that runs the backup (needs pg_dump, version >= server's 9.5)
echo '198.18.69.10:5432:ghost_dashboard:ghost_dash:<password>' > ~/.pgpass && chmod 600 ~/.pgpass
./scripts/backup.sh                     # test run -> /var/backups/ghost_dashboard/ghost_dashboard_<date>.dump

crontab -e                              # every Sunday at 02:00
0 2 * * 0 /opt/ghost_dashboard/scripts/backup.sh >> /var/log/ghost_backup.log 2>&1
```

Restore into an empty or scratch database, never over production:

```bash
createdb -h <host> -U <user> ghost_restore_test
pg_restore -h <host> -U <user> -d ghost_restore_test --no-owner ghost_dashboard_<date>.dump
```

Also copy the dumps off the machine (another host or share); `ghost_dash` needs `SELECT` on all tables.

## 5. Development and tests

```bash
# backend
cd backend && python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/pytest                      # parser tests only (DB tests are skipped)

# DB/API tests use a throwaway PostgreSQL 9.5 (never the production host: tests abort if they point at it)
docker compose -f docker-compose.test.yml up -d
TEST_DATABASE_URL=postgresql+psycopg2://test:test@127.0.0.1:5433/ghost_test .venv/bin/pytest

# frontend (dev server proxies /api to http://127.0.0.1:8000)
cd frontend && npm install && npm run dev
npm test && npm run build
```

Parser tests run against the real Jira comments in `backend/tests/fixtures/real_*.html`.
`real_derived_no_heading.html` is **derived** from a real comment with the metadata heading removed.
