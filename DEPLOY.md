# Deploying the dashboard to a server (plain VM)

This guide runs the whole stack (`api`, `sync`, `web`) with Docker Compose on a Linux VM. The PostgreSQL database
stays where it is (external). See [README.md](README.md) for what each part does.

```
users ──► VM:8080 (web/nginx) ──► api ──► PostgreSQL 198.18.69.10:5432
                                  sync ──► Jira (track-api.akamai.com, client certificate)
                                  sync ──► PostgreSQL
```

## 0. Checklist

| Need | Notes |
|---|---|
| Linux VM, 1 vCPU / 1-2 GB RAM, 5 GB disk | Any distro that runs Docker |
| Docker Engine + Compose plugin | Step 1 |
| VM can reach `198.18.69.10:5432` | The database. Step 2 |
| VM can reach `track-api.akamai.com:443` | Jira API. Step 2 |
| The DB admin allows the VM's IP | `pg_hba.conf`, step 2 |
| `.env` and `certs/` from the existing setup | Secrets, step 4 |
| Port 8080 (or your choice) open to users | Firewall, step 6 |

## 1. Install Docker on the VM

Ubuntu/Debian (use your company's approved Docker source if there is one):

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"      # log out and in again afterwards
docker compose version               # must print a version
```

RHEL/CentOS/Rocky: install `docker-ce` and `docker-compose-plugin` from the Docker repository, then
`sudo systemctl enable --now docker`. If SELinux is enforcing and the `certs` mount is unreadable, change the volume
in `docker-compose.yml` to `./certs:/certs:ro,z`.

## 2. Check connectivity and database access

From the VM:

```bash
nc -vz 198.18.69.10 5432             # database reachable?
nc -vz track-api.akamai.com 443      # Jira API reachable?
```

If the database does not answer, ask the DB admin to add the VM (PostgreSQL 9.5 uses `md5`) to `pg_hba.conf` on
198.18.69.10 and reload PostgreSQL:

```
host  ghost_dashboard  ghost_dash  <vm-ip>/32  md5
```

`listen_addresses` and the firewall on the DB server must allow port 5432 from the VM. The database already contains the
tables and the `v_dashboard` view; if it is a brand-new database, apply `db/schema.sql` first (README section 1).

## 3. Get the code onto the VM

Option A, git (recommended):

```bash
sudo mkdir -p /opt/ghost_dashboard && sudo chown "$USER" /opt/ghost_dashboard
git clone <repo-url> /opt/ghost_dashboard
cd /opt/ghost_dashboard
```

Option B, copy from your workstation (without build leftovers and secrets):

```bash
rsync -av --exclude node_modules --exclude dist --exclude .venv --exclude __pycache__ \
  --exclude .pytest_cache --exclude .env --exclude 'certs/*' \
  ./ghost_dashboard/ user@<vm>:/opt/ghost_dashboard/
```

## 4. Add the secrets (never committed to git)

Secrets are gitignored, so they must be copied separately. From your workstation:

```bash
scp .env user@<vm>:/opt/ghost_dashboard/.env
scp certs/sae-test.pem certs/sae-test.key certs/ca.pem user@<vm>:/opt/ghost_dashboard/certs/
ssh user@<vm> 'chmod 600 /opt/ghost_dashboard/.env /opt/ghost_dashboard/certs/*'
```

Or create `.env` on the VM from the template (`cp .env.example .env`) and fill in:

| Variable | Value |
|---|---|
| `JIRA_BASE_URL` | `https://track-api.akamai.com/jira` (the API host that accepts the client certificate) |
| `JIRA_BROWSE_URL` | `https://track.akamai.com/jira` (used for ticket links in the UI) |
| `JIRA_TOKEN` | Empty. The client certificate authenticates the sync |
| `JIRA_SSL_VERIFY` | `true` (never disable) |
| `JIRA_CA_BUNDLE` | `/certs/ca.pem` |
| `JIRA_CLIENT_CERT` / `JIRA_CLIENT_KEY` | `/certs/sae-test.pem` / `/certs/sae-test.key` |
| `DATABASE_URL` | `postgresql+psycopg2://ghost_dash:<password>@198.18.69.10:5432/ghost_dashboard` |
| `SOURCE_TICKET` | `GREL-799` |
| `SYNC_TOKEN` | A long random string: `openssl rand -hex 32` |
| `DASHBOARD_TZ` | `Asia/Kolkata` |
| `OWNER_REFRESH_DAYS` | `14` |
| `JIRA_FIELD_SQA` / `JIRA_FIELD_DEVQA` | Jira custom field ids, or empty to auto-discover by name |

Use the server IP for the database, never `localhost`. `TEST_DATABASE_URL` is only for tests and can be left out.

The CA bundle `certs/ca.pem` is the Akamai certificate chain the Jira API presents. To recreate it on a machine that
can reach Jira:

```bash
openssl s_client -connect track-api.akamai.com:443 -servername track-api.akamai.com \
  -cert certs/sae-test.pem -key certs/sae-test.key -showcerts </dev/null 2>/dev/null \
  | awk '/BEGIN CERTIFICATE/{p=1} p{print} /END CERTIFICATE/{p=0}' > certs/ca.pem
```

Check Jira access from the VM before starting (should print `200`):

```bash
curl -s -o /dev/null -w "%{http_code}\n" --cacert certs/ca.pem \
  --cert certs/sae-test.pem --key certs/sae-test.key \
  https://track-api.akamai.com/jira/rest/api/2/myself
```

## 5. Start the stack

```bash
cd /opt/ghost_dashboard
docker compose up -d --build
docker compose ps                    # api, sync, web should be Up
```

The services use `restart: unless-stopped`, so they come back after a reboot (Docker must start on boot:
`sudo systemctl enable docker`).

## 6. Open the firewall and verify

```bash
sudo ufw allow 8080/tcp              # Ubuntu; or firewall-cmd --add-port=8080/tcp --permanent && firewall-cmd --reload
curl -s localhost:8080/api/sync/status
```

Users open `http://<vm-name-or-ip>:8080`. API docs are at `/api/docs`.

### First sync

The `sync` service starts one sync on startup, then every 15 minutes. The first one reads about 2,000 comments and
takes a while over a remote database (well over half an hour in testing); the dashboard fills in as it goes.

```bash
docker compose logs -f sync                       # progress; "sync N: seen=... upserted=..." when done
curl -s localhost:8080/api/sync/status            # running / last_sync (status SUCCESS or FAILED)
curl -s "localhost:8080/api/runs?page_size=1"     # "total" grows while it runs
```

Trigger a sync manually (admins only):

```bash
curl -X POST -H "X-Sync-Token: <SYNC_TOKEN>" http://localhost:8080/api/sync   # 202 requested / 409 already running / 401 bad token
```

## 7. Run it in only one place

Stop the stack on your workstation once the VM works (`docker compose down`). Only one instance should sync against the
same database. The advisory lock prevents two syncs at the same time, but two workers are wasteful.

## 8. HTTPS and access control (recommended)

The dashboard has no login, so anyone who can reach it can read all results. Restrict it to your network or VPN, or add
authentication at a reverse proxy.

To serve HTTPS on a proper name with nginx on the VM:

1. In `docker-compose.yml`, publish the `web` port on localhost only: `"127.0.0.1:8080:80"`, then
   `docker compose up -d web`.
2. Add a proxy site (adjust the name and certificate paths):

```nginx
server {
  listen 443 ssl;
  server_name dashboard.example.com;
  ssl_certificate     /etc/ssl/certs/dashboard.crt;
  ssl_certificate_key /etc/ssl/private/dashboard.key;

  location / {
    proxy_pass http://127.0.0.1:8080;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
  }
}
```

Keep `X-Sync-Token` private: do not expose it in the proxy or the frontend.

## 9. Backups (optional)

See README section 4. In short: copy `scripts/backup.sh` to the VM, put the DB password in `~/.pgpass`, and add a weekly
cron entry. The data can also be rebuilt from Jira by running one sync.

## 10. Operating it

| Task | Command |
|---|---|
| Status | `docker compose ps`, `curl -s localhost:8080/api/sync/status` |
| Logs | `docker compose logs -f sync` / `api` / `web` |
| Update to a new version | `git pull && docker compose up -d --build` |
| Update only one service | `docker compose up -d --build api` |
| Restart | `docker compose restart` |
| Stop | `docker compose down` (does not touch the database) |
| Rotate `SYNC_TOKEN` or any `.env` value | edit `.env`, then `docker compose up -d --force-recreate` |

Rebuilding or restarting `sync` interrupts a running sync. This is safe: every comment is stored in its own
transaction and the next sync continues the work.

## 11. Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| `api` exits at startup, log says `v_dashboard is missing columns` | Apply `db/view_update.sql` to the database (README section 1) |
| API cannot connect to the database | VM not allowed in `pg_hba.conf`, firewall, or wrong `DATABASE_URL` |
| Sync log: `certificate required` | Client certificate missing or wrong path (`JIRA_CLIENT_CERT` / `JIRA_CLIENT_KEY`), or wrong host (must be `track-api...`) |
| Sync log: `CERTIFICATE_VERIFY_FAILED` | Missing or wrong `certs/ca.pem` (`JIRA_CA_BUNDLE`); recreate it as shown in step 4 |
| Sync log: `401 Unauthorized` | A wrong `JIRA_TOKEN` is set; leave it empty when using the client certificate |
| Dashboard shows "Syncing…" for a long time | The first sync is long; check `docker compose logs -f sync` and that the run count grows |
| "Last synced never" and no data | No successful sync yet; read `last_sync.error_message` from `/api/sync/status` |
| `POST /api/sync` returns 401 | Missing or wrong `X-Sync-Token`, or `SYNC_TOKEN` is empty in `.env` |
| Assignee / SQA / DevQA empty | Set `JIRA_FIELD_SQA` / `JIRA_FIELD_DEVQA` to the Jira custom field ids |
