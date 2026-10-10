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

## Client connections

Admin panel → Clients → Connections, or "+ Add connection" on a client company. Paste the client's
read-only key; it is locked on save and never shown again. "Sign in with…" tools (Salesforce, HubSpot,
RingCentral) use "Send connect link" instead. Twilio has a live test; other tools show "Saved, not tested"
until their connector is built.

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

Files: `Dockerfile`, `deploy/entrypoint.sh` (migrate, then Gunicorn), `deploy/docker-compose.yml`,
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

