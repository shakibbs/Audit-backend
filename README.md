# CiV backend (Django)

Django + Django REST Framework + PostgreSQL for the Comply iV Automated TCPA Audit System.

The client portal and the project docs live in their own repo: **[shakibbs/AUDIT](https://github.com/shakibbs/AUDIT)** (`frontend/`, `docs/`).
The two repos never import from each other; they talk only over `/api`.

## Run it

```bash
cp .env.example .env          # then fill in DJANGO_SECRET_KEY and CIV_SECRETS_KEYS (commands are in the file)
createdb civ                  # once
uv sync                       # install packages
uv run python manage.py migrate
uv run python manage.py createsuperuser   # your CiV admin login
uv run python manage.py runserver 8000
uv run pytest                 # tests
```

- CiV admin panel: http://localhost:8000/civ-admin/
- Health check: http://localhost:8000/api/health

**Never commit `.env`.** It holds `CIV_SECRETS_KEYS`, which unlocks the clients' saved API keys. Keep a safe
copy: if it is lost, saved keys cannot be read and must be entered again.

## Two separate doors

| | CiV staff | Client users |
|---|---|---|
| Sign in at | `/civ-admin/` (admin panel) | `/api/session/sign-in` (called by the portal) |
| Account table | `staff_user` (app `staff`) | `client_user` (app `accounts`) |
| Roles | Admin panel permissions | **Admin** or **Member**, plus "is our lawyer" |

Neither kind of account works at the other door. Passwords: Argon2 for new ones, bcrypt accepted and
upgraded; 12+ characters; 5 wrong tries in 15 minutes locks the email for 15 minutes.

## Layout (one app per module, one job per file)

| App | What it does |
|---|---|
| `config/` | Settings (read from `.env`), routes, health check, date formats |
| `apps/staff` | CiV team accounts (`AUTH_USER_MODEL`) |
| `apps/access_log` | Who did what, when. The database refuses edits and deletes |
| `apps/clients` | Client companies, lawyer-only mode, data access level 0–4 |
| `apps/accounts` | Client users, invites, and the login API (sign-in, sign-out, session, reset, invites, users) |
| `apps/connections` | Each client's tools (dialer, texting, certificates, lead feed, CRM): keys locked with Fernet, test, connect links, access level |
| `apps/admin_panel` | Admin panel look (Unfold theme styled like the portal), menu, dashboard, light/dark toggle |
| `apps/keyring` | Phone codes: each client's secret key (locked with `CIV_SECRETS_KEYS`), number cleaning to E.164, `Tokenizer`, `destroy_key` |
| `apps/ledger` | Fingerprint record (`fingerprint`) and `purge_log`; `ledger_job()` for every job that reads client records |
| `apps/anchoring` | Daily seal: Merkle root per client per day, RFC 3161 + OpenTimestamps stamps, `verify()` |
| `apps/tenancy` | Tenancy lock: Postgres row-level security on client-data tables, `tenant()` / `all_clients()` scopes, `create_app_role` |
| `apps/jobs` | Background workers (Celery + Redis): heartbeat every minute (proves the clock and workers are alive) |
| `tests/` | One folder per app |

## Client API

| Method + path | Who | What |
|---|---|---|
| `GET /api/session` | anyone | Who is signed in; sets the CSRF cookie |
| `POST /api/session/sign-in` · `sign-out` | anyone · signed in | Email + password |
| `POST /api/session/reset` · `reset/confirm` | anyone | Reset link (1 hour) and new password |
| `GET /api/invites/check` · `POST /api/invites/accept` | anyone with the link | Invite link (7 days) |
| `GET /api/users` · `POST /api/users` | signed in · Admin | List people · send an invite |
| `PATCH` / `DELETE /api/users/<id>` | Admin | Change role or lawyer mark · turn off access |

## Client companies and their connections

Admin panel → **Client companies** → click a company. One page holds everything about it:

- **Summary tiles:** data access level, connected tools, active users, open invites.
- **Tabs:** General (company details) · **Connections** · Users · Invites. **Activity** (latest access log
  entries) sits under the tabs; "Full access log" opens all of them.
- **Connections are added on this page**, also when creating a new company: fill in the company, add its
  tools on the Connections tab, and one Save keeps both. Keys are locked on save and never shown again
  (leave the fields empty to keep a saved key). Each tool has a button: **Test connection now**, or for
  "Sign in with…" tools (Salesforce, HubSpot, RingCentral) **Send connect link to client Admins**.
  Twilio has a live test; other tools show "Saved, not tested" until their connector is built.
- There is no separate Connections page, and no separate Client users or Invites page: people are added and
  edited on the **Users** tab (a new person gets an email link to set their own password). The client list's
  search also finds a person by name or email.
- **Onboarding card** (`apps/onboarding`): 7 steps with a progress bar. Agreement, Annex C, campaigns and
  first sync are ticked by hand (Agreement and Annex C also tick when that document is uploaded); dialer,
  texting and client Admin tick themselves.
- **Stage** (General tab): Trial · Onboarding · Active · Paused · Ended, with a reason and a **Stage history**.
  Ended blocks the client's sign-in; Paused will stop live sync (`Client.can_sync`).
- **Contract & billing** tab (`apps/billing`): price, period, payment method, start and renewal dates,
  auto-renew, notice period, billing contact, notes. Renewal shows under the name, in the list ("Renews",
  amber inside the notice period) and on the dashboard.
- **Documents** tab (`apps/documents`): agreement, Annex C, signed statements, DPA, other. Upload a file
  (PDF, image, Word; 20 MB max) or add a link. Files are fingerprinted (SHA-256), stored privately in
  `MEDIA_ROOT` (Docker volume `civ_media`) and opened only by CiV staff; opening is logged.
  Never the client's customer records.

## Background workers (Module 1, step 1)

Jobs that run by themselves (reading tools, the nightly seal, …) use **Celery**, with **Redis** as the to-do list.
Each app keeps its jobs in `tasks.py`; the timetable is `CELERY_BEAT_SCHEDULE` in `config/settings.py`.

- **Locally:** leave `REDIS_URL` empty and a job runs at once, in the same process. No Redis needed.
  To run real workers: set `REDIS_URL=redis://127.0.0.1:6379/0`, then `uv run celery -A config worker -l info`
  and `uv run celery -A config beat -l info`.
- **Server:** containers `redis` (keeps nothing on disk), `worker` and `beat` (the clock) start with the rest.
- **Check:** the `job_heartbeat` row's time updates every minute when the clock and workers run.

## Phone codes (Module 1, step 2)

CiV never saves a phone number. Inside a job, a number becomes a **phone code** (`phone_token`):
HMAC-SHA256 of the cleaned number (E.164) with the client's own secret key.

- Same number, same client → same code (so contacts can still be counted). Same number, two clients → different codes.
- Each client's key is made on first use, kept **locked** with `CIV_SECRETS_KEYS` (decision D19 = A: CiV holds it),
  and opened only in memory. Its ID (`kid`, e.g. `k1`) is saved next to every code.
- `destroy_key(client)` at contract end wipes the key: codes already saved can never be linked to a number again.
  Logged in the access log.
- Use: `codes = Tokenizer(client)` once per job, then `codes.token('(916) 555-4471')`.

## Fingerprint record (Module 1, step 3)

CiV proves what it read without keeping it. Every record a job reads gets one `fingerprint` row: client, SHA-256 of
the **exact bytes received**, tool, the record's ID there, kind, source grade (A–D, spec §4) and fetch time. Never the
content, a phone number or a name.

```python
with ledger_job(client, 'twilio sync') as job:
    job.record(source_system='twilio', source_record_id=sid, raw=response_bytes,
               content_kind=ContentKind.TEXT, source_grade=SourceGrade.C)
```

If the job fails, every row it wrote is removed and one `purge_log` line says how many and the error's type (never its
message, which could quote a record).

## Daily seal (Module 1, step 4)

Every night at 00:30 UTC (`seal_nightly`), each client's fingerprints from each finished day are joined into one
**Merkle root** (`merkle_anchor`). Each fingerprint keeps its `merkle_path`, so it can be checked alone.

- The root is stamped by two outside services: an **RFC 3161** time-stamp authority (`ANCHOR_TSA_URLS`, default
  FreeTSA, then SSL.com) and **OpenTimestamps** (`ANCHOR_OTS_CALENDARS`, Bitcoin-backed; the proof is pending until
  a block confirms it). The signed answers are kept whole.
- A service that is down does not stop the seal: the root is kept and `stamp_missing` retries every hour.
- `verify(fingerprint)` → `matches`, `changed` (the row, including its read time, was altered after sealing) or
  `not_sealed` (read today).

## Tenancy lock (Module 1, step 5)

The **database itself** keeps clients apart (decision: shared tables + row-level security). Every table of client
data is locked with `apps.tenancy.sql.lock_table` in its migration (ENABLE + FORCE row-level security, policy on
`client_id`). A locked table shows **nothing** until the work says whose rows it may see:

```python
with tenant(client): ...      # one client's rows (jobs; later, portal requests)
with all_clients(): ...       # every client (CiV's own nightly jobs)
```

- Locked now: `client_key`, `fingerprint`, `purge_log`, `merkle_anchor`. A test fails if a new table with
  `client_id` is not locked. CiV's business tables (companies, users, contracts, documents, access log) are read by
  the admin panel across clients and are not locked.
- Superusers skip every lock, so on the server the app runs as a **limited user** (`DB_APP_USER` /
  `DB_APP_PASSWORD` in `.env.production`): no superuser, no BYPASSRLS. When `DB_APP_USER` is set, the backend,
  worker and clock log in as it (`config/settings.py`). `entrypoint.sh` applies database changes as the owner
  (`DB_AS_OWNER=1`), then runs `create_app_role` (creates or refreshes the limited user and its rights) on every start.

## Use it with the portal

In the portal repo, put `BACKEND_URL=http://localhost:8000` in `.env.local` and restart `npm run dev`.
While building, emails (reset and invite links) print in this terminal.

## Deploy on a server that already runs Traefik (Docker)

Used for the Hostinger VPS that also runs n8n. n8n is never touched: CiV's containers carry Traefik
labels, and Traefik routes `app.…` to the portal and `admin.…` to the admin panel, with HTTPS.

| Container | What | Reachable from |
|---|---|---|
| `portal` | Next.js portal (built from the AUDIT repo) | `https://APP_DOMAIN` |
| `backend` | Django + Gunicorn | `https://ADMIN_DOMAIN` (admin panel only) and the portal, inside Docker |
| `redis` | The workers' to-do list (Redis 7, nothing on disk) | backend, worker and beat only |
| `worker` · `beat` | Background jobs and their clock (same code as the backend) | nothing outside Docker |
| `db` | PostgreSQL 17, data in the `civ_pgdata` volume | the backend only |

```bash
# once: both repos side by side
mkdir -p /opt/civ && cd /opt/civ
git clone https://github.com/shakibbs/Audit-backend.git
git clone https://github.com/shakibbs/AUDIT.git
cd Audit-backend/deploy
cp .env.production.example .env.production   # fill it in (comments inside)
docker compose --env-file .env.production up -d --build
docker compose --env-file .env.production exec backend python manage.py createsuperuser

# update by hand (normally automatic, see below)
/opt/civ/deploy.sh

# look
docker compose --env-file .env.production ps
docker compose --env-file .env.production logs -f backend
```

Files: `Dockerfile`, `deploy/entrypoint.sh` (migrate and refresh the limited user as the owner, then Gunicorn), `deploy/docker-compose.yml`,
`deploy/.env.production.example`. In production, WhiteNoise serves the admin panel's styles.

## Automatic updates (GitHub Actions)

Every push to `main` in **either** repo runs that repo's tests on GitHub. Only if they pass, GitHub logs in
to the server and runs `/opt/civ/deploy.sh` (a copy of `deploy/update.sh`): pull both repos, rebuild only
CiV's containers, check the backend and portal answer. Results: the repo's **Actions** tab (✅ or ❌).

- `.github/workflows/deploy.yml` here; the portal repo has its own (it skips docs-only pushes).
- Repo secrets (both repos): `DEPLOY_SSH_KEY` (private key), `DEPLOY_KNOWN_HOSTS` (server identity),
  `DEPLOY_HOST` (server IP).
- On the server the key is locked in `/root/.ssh/authorized_keys` with
  `command="/opt/civ/deploy.sh",restrict`: it can run the update script and nothing else.
- After changing `deploy/update.sh`, copy it again: `cp /opt/civ/Audit-backend/deploy/update.sh /opt/civ/deploy.sh`.
- A commit message containing `[skip ci]` pushes without deploying.

