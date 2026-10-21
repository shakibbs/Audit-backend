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
| `apps/rulebook` | Rulebook: versions and rule values (federal, state, forum; effective-dated), loaded from `rulebook/*.yaml` |
| `apps/regulatory` | Regulatory changes (laws, orders, court rulings) and the Rulebook rules each touches; admin page |
| `apps/sync` | Live sync engine: adapter shape, bookmarks (`sync_cursor`), gaps (`sync_gap`), timetable, health, `/hooks/<id>` |
| `apps/certificates` | Consent certificates (TrustedForm, Jornaya): found in synced records, claimed within 72 hours, facts kept |
| `apps/contacts` | Normalizer: every synced call or text → one `contact_event` row, same shape for every tool |
| `apps/imports` | Uploaded lists: CRM records' creation facts grouped into import batches (bulk / small / by hand / feed) |
| `apps/optouts` | The STOP list (`opt_out_event`) and opted-out numbers re-added in uploads (M34) |
| `apps/reconcile` | Records completeness (M37): what CiV read vs the bill, days present, STOP replies, monthly volume |
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

## Rulebook (Module 2, step 1)

Every legal setting and parameter the engine uses lives in **`rulebook/v3.0.yaml`** (from the spec
`02-rulebook-parameters.md` v3.0): 146 rules, plus state rows (calling hours FL, OK, MD, CT, TX; frequency limits
FL, OK, MD) and the Fifth Circuit forum row. Each rule has its meaning, owner, status, counsel item, whether it can
change a result, its value (or, for TBD, a provisional value / strict and lenient variants for draft runs only)
and the plain words shown in the portal.

- **Status:** `set` decided · `proposed` runs, results provisional · `tbd` never runs in a scored run (RULE_PENDING).
- **Change a rule:** edit the file, push; `load_rulebook` runs on every start and reloads a changed draft or
  provisional version. An **approved** version never changes: add a new version file instead.
- **The loader refuses** (spec §2): a missing or unknown key, a key listed twice, `vs_rate_weights` not adding up
  to 1, `dedupe_window_seconds` below `clock_skew_seconds`, a Set or Proposed rule without a value, and in an
  approved version any TBD key or a result-changing key without counsel approval.
- v3.0 is **provisional**: 70 set, 55 proposed, 21 TBD. Before any approved version, counsel must also approve
  5 result-changing keys not yet marked counsel-approved (cert expiry hours ×2, conv_review ×3).

### Looking a rule up (Module 2, step 2)

```python
rules = RuleSet()                                   # one per run: the whole rulebook in memory, no more queries
hours = rules.get('calling_hours', on=contact_date, state='FL')
hours.value        # {'start': '08:00', 'end': '20:00'}, or None while pending
hours.provisional  # True: Proposed (or TBD) → the result is marked provisional
hours.pending      # True: TBD → the check returns not_run, RULE_PENDING
```

- **Place:** the state (or court `forum=`) first, then federal. A place's own rule wins even while it is TBD.
- **Date:** the row in force on that day (`effective_from` / `effective_to`).
- **Mode:** `client` = approved rulebooks only · `internal` (default) = approved or provisional · `draft` = also
  TBD test values and `variant='strict' | 'lenient'` (tests and the impact view).

### Business days (Module 2, step 3)

`apps/rulebook/business_days.py` counts business days as the Rulebook says (`business_day_calendar`: Mon–Fri except
observed US federal holidays, on the **recipient's** own date).

```python
deadline = optout_deadline(stop_received_at, time_zone='America/New_York')
deadline.date         # STOP on Fri 20 Nov 2026 → Mon 7 Dec 2026 (Thanksgiving skipped)
deadline.provisional  # True while optout_deadline_business_days is Proposed
BusinessCalendar().between(start, end)   # e.g. business days a request took to reach the list (M42)
```

- Day 1 is the first business day **after** the opt-out day. Weekend holidays are skipped on the observed day.
- Time zone order (`business_day_tz_fallback`): ZIP, then area code, then America/New_York (the earliest deadline);
  `pick_time_zone()` applies it. The ZIP and area-code tables come with Module 4 (normalizer).

### Regulatory changes and the admin Rules pages (Module 2, step 5)

Admin panel → **Rules**:
- **Rulebook**: every rule by place, read only, with search and filters (status, owner, section, place, "changes
  results"). Rules still change only in `rulebook/*.yaml`; edit and approve screens come in Module 13.
- **Regulatory changes**: CiV staff add, edit and remove law changes (status, dates, plain-words summary, rules it
  touches picked from the Rulebook, metrics, source, counsel check). Unknown rule keys, bad metric codes and banned
  words are refused; every add, edit and removal is logged.
- **Rule updates tab** on a law change (Module 2, step 5b): one line per rule value the law brings. **Modifies rule**
  = pick the existing rule; leave it **blank for a brand-new rule** and give its name and meaning. Each line stays a
  **Draft** until an admin with "Can approve rule updates" clicks **Approve** on that page: the old value then ends
  the day before the start date and the new one starts, so there is always one value per rule, place and day
  (overlaps refused). **Reject** keeps the line on record, unused. Both are logged. Approved updates are re-applied
  whenever the Rulebook file is reloaded.
- Starting items: the four from the portal's sample data, marked "to check" for counsel.

### Portal pages and lawyers' reviews (Module 2, step 6)

| Method + path | Who | What |
|---|---|---|
| `GET /api/rulebook` | signed in | Rules in force today (federal + state rows), counts, and a note while the version is not lawyer-confirmed |
| `GET /api/rulebook/calendar?year=` | signed in | Calendar & hours: holidays, next holiday, calling hours and limits by state, opt-out timing, time-zone order |
| `GET /api/reg-changes` | signed in | Law changes with their draft / approved rule values and this company's own review and "read" mark |
| `POST /api/reg-changes/<id>/confirm` | signed in | "I've read this", for the whole company |
| `POST /api/rule-updates/<id>/review` | the company's lawyer | Agree / disagree + comment on a **draft**; can be changed until CiV decides |
| `POST /api/reg-changes/suggest` | the company's lawyer | Tell CiV about a law change; only CiV sees it (admin → Rules → Client suggestions) |

- Reviews are advice: the admin page shows "N agree · N disagree" with comments next to each draft; **CiV alone
  approves**. Reviews, read marks and suggestions are client data: locked per client (row-level security).
- `apps.tenancy.middleware.TenantScopeMiddleware` opens the rows for each request: CiV staff in the admin panel see
  every client; a signed-in client user sees only its own company; anyone else sees no client data.
- Spec key names containing banned words are shown under a plain name (`direct_violation_grade` →
  `direct_contact_cap_grade`).

## Live sync engine (Module 3, step 1)

Every client tool is read by one engine (`apps/sync`); each tool is a small adapter (`Connector`) answering:
*what changed since this bookmark?* · *list everything* (weekly check) · *what is in this live notice?* (signature
checked). Adapters are registered in `apps.sync.connector.CONNECTORS`; until a tool's adapter exists, it is not read.

- **Timetable** (Celery beat): poll every 2 min · catch-up every hour · full check
  weekly · health every 10 min. Each run reads `SYNC_BATCH_SIZE` (500) records and queues the next turn at the back
  of the line, so a big client never holds up a small one.
- **Each record:** fingerprinted (exact bytes), phone numbers turned into phone codes, handed to
  `apps.sync.handoff` (Module 4 plugs in there; until then only counted), then dropped. A record seen before with
  the same content is skipped; a changed one is processed again.
- **Bookmarks** (`sync_cursor`) move only after a batch is fully processed (one transaction), so a crash never skips
  or doubles a record; a failed batch leaves no rows and one `purge_log` line. The weekly check keeps its own bookmark.
- **Gaps** (`sync_gap`): a change on a live tool found by the catch-up or full check instead of a live notice.
- **Live notices are OFF** (owner decision 2026-10-16): there is no public door; CiV asks each tool every **2 minutes**,
  which meets the 15-minute urgent-alert goal. The door's code (`apps/sync/views.py`, adapter signature checks) stays
  and is tested; it answers at `/hooks/<connection id>` only if `SYNC_HOOKS_ENABLED=true` and a server route is added.
- **Health:** Live · Catching up · Stale (quiet longer than the Rulebook's `source_freshness_hours`, 2). Going stale
  or coming back is logged and the data access level is recalculated. Paused or ended clients are not read.
- Bookmarks and gaps are client data (tenancy lock).

### Twilio (Module 3, step 2)

`apps/sync/connectors/twilio.py`, built from Twilio's API docs (not yet tried on a real account). Uses the
Connection's Account SID (`account`) and auth token (`key`). Reads **texts and calls**.
- **Polled every 2 minutes:** `Messages.json` by `DateSent` and `Calls.json` by `StartTime`, one day at a time, all
  pages, read oldest first; texts get half of each batch, calls the rest. Each has its own bookmark
  `<time>#<how many at exactly that time are done>` (stored together as JSON). The newest 2 minutes wait for the next
  run. Starts at the client's start date. A row whose status changed is read again.
- **Live notices (off):** the adapter can check Twilio's `X-Twilio-Signature` (verified against Twilio's official
  library), ready if the door is ever opened.

### Convoso (Module 3, step 3)

`apps/sync/connectors/convoso.py`, built from Convoso's API docs (not yet tried on a real account). The Connection
holds the auth token (`key`) and the **account time zone** (`secret`, e.g. `America/New_York`): Convoso gives call
times in that zone and CiV turns them into UTC, so a wrong zone would shift every calling-hours check.
- Polled every 2 minutes: `POST /v1/log/retrieve` (token in the body, not the URL) by time range, one hour at a time,
  all pages (`limit` + `offset`), oldest first; bookmark `<time>#<n>`. Each call's number, number dialed and caller
  ID become phone codes. A changed result code is read again (weekly full check).
- **Test connection** checks the time zone and reads one call from the last hour.

### Five9 (Module 3, step 3)

`apps/sync/connectors/five9.py`, built from Five9's Configuration Web Services docs (SOAP; not yet tried on a real
account). The Connection holds a reports-only user (`account`), its password (`key`) and the **report time zone**
(`secret`).
- Five9 gives call logs as reports: `runReport` (folder "Call Log Reports", report "Call Log") for one hour →
  `isReportRunning` until done (about 2 minutes at most, else retried next turn) → `getReportResultCsv`. The whole
  hour is processed at once (one report per window); bookmark = the window's end. The newest 5 minutes wait.
- Read **every 10 minutes at most** (`min_poll_minutes`; any adapter can set its own gap). Columns matched loosely
  (CALL ID, TIMESTAMP or DATE + TIME, ANI, DNIS); report folder, name and columns to confirm on a real account.
- **Test connection** checks the time zone and runs the report for the last minute.

### Vicidial (Module 3, step 3)

`apps/sync/connectors/vicidial.py`. Each call center runs its own Vicidial, so CiV reads the call log tables through
a **read-only database account on the client's server** (CiV connects out; nothing opens on CiV's side). The
Connection holds `host:port/database` (`account`, database usually `asterisk`), the user (`key`) and password
(`secret`). Uses PyMySQL. Built from Vicidial's table layout; not yet tried on a real server.
- Polled every 2 minutes: `vicidial_log` (outbound) and `vicidial_closer_log` (inbound), half a batch each, oldest
  first by `start_epoch` (universal time: no time-zone setting) then row ID; bookmark per table `<epoch>|<id>`.
  Only `SELECT` of the needed columns is ever sent. The newest 2 minutes wait.
- **Test connection** reads one row from each table and says whether the login, the network or the SELECT right
  is the problem.

### Consent certificates (Module 3, step 4)

`apps/certificates`. Every synced record (dialer, CRM…) is scanned for a **TrustedForm** certificate link
(`cert.trustedform.com/<40 hex>`) or a **Jornaya LeadiD** token (a UUID in a field named for LeadiD/Jornaya). Each is
queued once per client with a deadline = lead time + `cert_unretained_expiry_hours` (72).
- **Claim queue every minute, nearest deadline first:** TrustedForm is claimed (Retain + Insights, api-version 4.0)
  with the client's key; Jornaya is looked up (request format **to confirm** on a real account). Vendor down → retried
  each minute until the deadline. Not found or past the deadline → **lost** (logged). No certificate account
  connected → waits as "no key" (a key added before the deadline still works). Still unclaimed 12 hours before the
  deadline → logged once.
- Kept: created / expires dates and the form's host + path only (no query string). The vendor's answer is
  fingerprinted (source grade B) and dropped. Consent itself is judged in Modules 6 and 7.
- **Test connection** asks about a made-up certificate: "not found" = key works, "refused" = bad key.

### CRMs: Salesforce and HubSpot (Module 3, step 5)

Adapters only (`apps/sync/connectors/salesforce.py`, `hubspot.py`), built from the vendors' REST docs; not yet tried
on real accounts. They use the client's access pass from "Allow" (stored locked on the Connection) and renew it with
CiV's app registration (`SALESFORCE_CLIENT_ID/SECRET`, `HUBSPOT_CLIENT_ID/SECRET` in `.env`; `apps/sync/connectors/oauth.py`).
A refused renewal = **Disconnected** (the client must click Allow again). **Not built yet:** the "Allow" flow and the
portal's Connect button, and registering CiV's developer apps.
- **Salesforce:** Leads, Contacts and call Tasks changed since the bookmark, `FIELDS(ALL)` 200 at a time, oldest first
  by `SystemModstamp` then `Id`; bookmark per object `<stamp>|<id>`.
- **HubSpot:** contacts and calls through the search API by `hs_lastmodifieddate` (ascending, 100 a page); bookmark per
  object `<ms>#<n>`. Asks for the needed properties plus any TrustedForm / LeadiD / Jornaya property.
- Certificate links in any CRM field reach the 72-hour claim queue.

### Sync made visible (Module 3, step 6)

- **Admin → client page → Connections tab:** a read-only **Sync** column per tool: Live · Catching up · Stale · Never
  read, last read, records read, last problem (e.g. "Five9Error, 4× in a row"); "waiting for the client to click
  Allow" for CRMs; "Not read yet" for tools whose adapter is not built.
- **Admin → client page:** a **Certificates** tile (claimed · waiting · no key · lost).
- **Portal API:** `GET /api/sources` (the client's real tools with Live/Stale/Not supplied, plus the same five upload
  types the Upload centre offers) and `GET /api/data-health` (access level, tools live/stale/not connected, last
  change; records completeness and conversation review are `null` = not yet measured, until Modules 5 and 9).

## Contacts: one shape for every tool (Module 4, step 1)

`apps/contacts` is a sync hand-off receiver: each synced call or text becomes one **`contact_event`** row (spec
§contact_event), whatever the tool. `translators.py` holds one small translator per tool (Twilio texts + calls,
Convoso, Five9, Vicidial, HubSpot calls); CRM leads and people are not contacts (they serve consent and lead source
later); Salesforce call Tasks carry no number, so the dialer's copy of the call is used.
- Fields: the person as a **phone code**, caller ID shown as a phone code, channel, direction, time (UTC), end, length,
  answered, the tool's own result code **kept as is** (the AI judges stop requests, Module 9), SMS status, campaign,
  agent, the tool's lead ID, tool + record ID, source grade. Dial mode, prerecorded/AI and STIR stay empty
  (= unknown, never worst case) until a tool provides them.
- A changed record updates its contact (one row per tool record). Never the number, a name or the message text.
  Locked per client.

### Where the person is (Module 4, step 2)

`apps/contacts/location.py`: while the number is in memory, each contact gets the person's probable **state**,
possible **time zones**, **country**, whether it is **outside the US** (US territories such as Puerto Rico are not),
and a **confidence**: `medium` = area code with one zone; `low` = several possible zones or unknown (the Rulebook's
`location_uncertain_levels`: reported as "possible", never dropped; checks use the strictest zone); `high` is kept
for a ZIP code, added when lead data is joined (Modules 6/8). Built on the phonenumbers library's offline data plus
corrections for US area codes that span two zones and the other +1 countries' zones — **corrections to verify
against NANPA / tz data**. `ContactEvent.local_times()` gives the contact's time in each possible zone.
Only state / zones / country are kept, never the number. Contacts saved before this step have no location.

### Same call from two tools (Module 4, step 3)

`apps/contacts/dedupe.py`: the same call or text recorded by two tools is counted once. Same person (phone code),
same channel, same direction (or one unknown), **different tools**, and **calling times** (when it happened, not when
CiV read it) within `dedupe_window_seconds` (120, never below `clock_skew_seconds`). A group never holds two records
from one tool (one tool does not record one call twice), so a copy joins the nearest call only. Nothing is deleted:
copies share `dedupe_group`; the main record (`is_primary`, the one counted) is the tool that made the contact before
a CRM, then the earliest. A corrected time re-groups. Count contacts with `is_primary=True`.

### Phone epochs: who had the number when (Module 4, step 4)

`apps/contacts/epochs.py`: numbers get recycled, and one owner's consent never covers the next. Each number (phone
code) has a timeline of **epochs** (`phone_epoch`: number, start, end, reason, signal source); every contact is
attached to the epoch it happened in. `split(client, token, at, reason, source)` starts a new owner from `at`: the
earlier epoch ends there and later contacts move; nothing is deleted; an earlier change learned later is placed in
time order.
- **Signal now:** a number that **moved** between CRM customer records (`crm_phone_holder`, record IDs only): every
  earlier record let go of it and a different record has it. A number on two records at once is a duplicate or a
  household, not a new owner.
- **Later signals** call `split()`: "wrong number" replies (Module 9), the client's reassigned-number results, a new
  consent from someone else (Module 6). Until then most numbers have one epoch. Locked per client.

### Contact Ledger, number page, "Can I call now?" (Module 4, step 5)

- Each contact keeps a **masked label** only (owner decision D31): area code + last 4, e.g. `(916) •••-0001`; the
  middle digits are never kept.
- `GET /api/contacts` (status, q, channel, direction): counted contacts newest first (copies from a second tool shown
  once, flagged "seen in N tools"), where the person probably is, the tool's result code, consent **"Not checked
  yet"** (Module 6). `q` = a full number (turned into a phone code with the client's key, never stored) or its last 4.
- `GET /api/evidence/p-<24 hex>`: a number's page by its portal address (part of its phone code, never the number):
  contacts, owners (epochs), and the **calling window** now (allowed hours in the person's own time for each
  possible zone, the stricter decides; draft hours said to be draft; state holidays "not set yet").
- `POST /api/can-call {number}`: where the person probably is and whether now is inside their hours. Not stored.
  Advice only: CiV never blocks a call.

## Uploaded lists (Module 5, step 1)

`apps/imports` (spec §5a, creation bursts). Every synced CRM person or lead notes **when, by whom (the CRM's user ID)
and how** it was created (`crm_creation`; Salesforce CreatedDate / CreatedById; HubSpot createdate /
hs_created_by_user_id / hs_object_source). Every 15 minutes each user's records are regrouped into **batches**
(`import_batch`): a gap over `import_gap_seconds` (120) starts a new one; n ≥ `import_min_batch` (20) = **bulk import**,
1 = typed by hand, else small batch. HubSpot's own **IMPORT** label makes a bulk import at any size.
- **Feeds are not uploads**, recognised without per-client settings: the tool says INTEGRATION / API, or the user
  creates records on ≥ 5 days and ≥ 10 hours of the day within 2 weeks (a steady stream, not a burst).
- `origin(client, phone_token, at)` = the batch the number came from (for M32 and the provenance ladder later).
- Only user IDs and times are kept, never names or file names. Dialer-side list imports come later. Locked per client.
  Batches are rebuilt from scratch each run (fine at pilot scale).

## The STOP list and re-added numbers (Module 5, step 2)

`apps/optouts`: the STOP list (`opt_out_event`, phone codes only) is filled as records arrive:
- an inbound text whose **whole message** is one of the Rulebook's `optout_keywords` ("STOP", "Stop!", "unsubscribe";
  not "Stop by tomorrow?"), read in memory, text never stored;
- a Salesforce **Do Not Call** box ticked on a lead or contact.
The tool's own result codes are not used here; Module 9 (AI) adds plain-word opt-outs to the same list.
After each batch rebuild, every upload (bulk or small batch) is checked: a number that opted out **before** the record
that brought it back is a **re-added** number (`optout_readded`, M34, double weight in F3). The batch shows the count,
and each find is logged once.

## Records completeness (Module 5, step 3)

`apps/reconcile` (spec §5b, M37), every night for this month and last. Per measure (`reconciliation`):
- **texts / calls:** outbound records CiV read from a tool ÷ what that tool **billed** (Twilio Usage Records, daily,
  `sms-outbound` / `calls-outbound`). Under `completeness_floor` (0.9) = flagged; above 100% = listed for review.
- **vendor leads**, and calls through dialers: no billing API yet → **not available**, left out of M37, never failed.
- **days_present:** days with at least one contact ÷ working days (business-day calendar); flags under 0.9.
- **stop_replies:** zero STOP replies while more than `stop_check_min_texts` (1,000) texts were sent: flagged.
`period_integrity` per month: **M37** = the lowest available ratio of calls / texts / vendor leads; under the floor =
**"incomplete data"** (the missing share takes worst-case values in Module 10, the client's missing data, not CiV's
work); every measure that flagged; and the counted contacts (the Exposure's Volume input). Locked per client.
`GET /api/data-health` now carries the latest month's **records completeness** for the Overview box:
`completenessStatus` (complete / incomplete / not_available / not_measured) and a one-line `completenessNote`.
**Every tool is checked, the best way it allows** (`apps/reconcile/check.py`, field `method`): 1 **bill** (Twilio) ·
2 **tool's own total**, one request per tool and month (`Connector.counts` + `count_between`: Convoso `total_found`,
Five9 Call Log report rows, Vicidial `COUNT(*)` on both call tables, Salesforce `COUNT()` of leads + contacts created,
HubSpot search `total` of contacts created and calls) · 3 **volume pattern** when neither exists or the total could
not be read: working days with records from that tool, plus a sudden drop (last 7 days under a quarter of the 4 weeks
before). M37 = the lowest available ratio over all tools; a tool CiV cannot read yet is "not available".
**Admin → client page:** a **Records completeness** tile beside Users and Certificates (`apps/reconcile/summary.py`):
the latest month's overall %, Complete / Incomplete, how many tools, and the lowest one. **Clicking it opens**
`/civ-admin/clients/client/<id>/completeness/`: this month and last, one table each, one line per tool (how measured,
numbers, %, status), with the extra checks (days with any records, STOP replies) as rows marked "not in %".

## Made visible after Module 5

- **Number page seal:** `GET /api/evidence/…` `anchor` is real: sealed when every record of the number is in a sealed
  day, the latest seal date and root, `sealedCount` / `recordCount`, and whether the outside time stamp arrived.
- **Opt-outs card:** `GET /api/optouts`: the STOP list, one row per number (its latest opt-out), newest first, with
  the masked label, how (e.g. "Text · keyword"), the deadline in business days in the person's time zone (provisional
  while the 10 days are Proposed), business days left, counted contacts after the opt-out (before / after the
  deadline), and `dialerMarked` (Module 9 step 3: yes / no / null = not checked).
- **Admin → Records:** read-only **Failed-job cleanups** (`purge_log`) and **Missed records** (`sync_gap`, empty while
  every tool is polled).

## Proofs of permission (Module 6, step 1)

`apps/consent` (spec §5): a hand-off receiver (`proofs.proofs_seen`, after the certificate queue) files each proof
in `consent_proof`, one row per number (phone code) and owner (epoch). Facts only, never a certificate's content.

- **Certificate:** a TrustedForm / Jornaya link in a lead, CRM or dialer record, tied to its claim. Until the claim
  is read the record's time stands in (`date_known = false`); every 5 minutes `refresh_proof_dates` gives it the
  certificate's real creation time and the right owner.
- **Self-asserted:** a CRM field named for consent (not opt-out / revoked) set to yes. Never enough alone.
- **Existing customer:** HubSpot's "became a customer" date (`hs_lifecyclestage_customer_date`) → purchase.
- **Owner:** a proof belongs to the owner of the number on the consent date; owner 1's proof never covers owner 2.
- **Evidence folder:** `evidence_folder(client, token, epoch)` = the owner's proofs plus the uploaded list the number
  came from; `manual_import_no_evidence` when it came from a list and nothing but a CRM box backs it.
- Locked per client like the other client tables.

### What proof a contact needs (Module 6, step 2)

`apps/consent/needs.py` (spec §5 "before the checks"), every minute for new contacts, with the rules in force on the
contact's date. One `consent_need` row per contact and variant (strict and lenient while rules are undecided; the
portal shows strict). Rulebook lookups now accept `variant=` outside draft runs for keys that are not yet Set.

- Every campaign counts as marketing (label `category_unknown`): same for every client, strictest.
- Robocall: autodialed mode, unknown mode (`dial_mode_unknown`; lenient: only prerecorded/AI counts), prerecorded or
  AI voice, or a marketing text (`sms_treated_as_autodialed`).
- Bases and what each needs: `robocall_marketing` → written consent types · `dnc_listed` (on the STOP list before the
  contact) → signed written or a current customer · `dnc_unknown` (no do-not-call list supplied, label
  `dnc_list_not_supplied`) → any accepted proof · `state_law` when a state rule is set · `civ_policy` otherwise.
- `meets()`: a CRM box never meets a need; an existing customer counts only within 18 months (purchase) / 3 months
  (inquiry), only for live hand-dialed calls, never robocalls or texts.
- Inbound contacts and CiV test numbers need nothing.
- **STOP list** (`opt_out_in_force`): a STOP counts only while in force: not for the one confirmation text within
  `confirmation_window_minutes`, not before the grace days end (lenient 10, strict 0), and no longer once the person
  gives a new consent (certificate) after it. A purchase or CRM box never lifts it.

### The five checks (Module 6, step 3)

`apps/consent/checks.py` (spec §5), right after "what is needed", for every new contact; one `consent_result` row per
contact and variant: status **verified / weak / pending / conflicting / no_proof** (or not_needed for inbound and
test numbers), the primary code and every code of the deciding step, each basis's status and winning proof, labels,
`evaluation_as_of` and the Rulebook version. Locked per client.

1. **A fitting proof** for the owner (epoch): NP_NONE, NP_SELF_ASSERTED, NP_NO_EVIDENCE_FOUND (uploaded list),
   NP_BEFORE_CONSENT (linked by lead ID: no tolerance; unlinked: `clock_skew_seconds`), NP_AFTER_OPT_OUT,
   NP_RELATIONSHIP_LAPSED, NP_WRONG_TYPE.
2. **Opens at its source:** a lost claim → CF_EXPIRED (`pre_engagement` label if before the client started), the
   provider does not have it → CF_NOT_FOUND; not read yet → **pending** (PD_NOT_READ_YET / PD_NO_CERT_ACCOUNT).
3. **Consent wording, pre-ticked box:** not measured yet (Module 7).
4. **Sources agree:** certificate made after the lead was delivered (CRM creation time) → CF_CERT_AFTER_DELIVERY
   (within the clock tolerance → weak). Phone and page match: not measured yet (Module 7).
5. **Complete:** WK_TIMING_UNCERTAIN, WK_RETENTION (expires within `cert_expiry_warning_days`).
All pass → VF_OK; an existing customer alone → label `EBR_ONLY`. Best proof per basis (ties: newest), worst basis
wins. Checks not measured yet are listed as `not_measured:*` labels and never change a result.

### Keeping results up to date (Module 6, step 4)

`apps/consent/keeping.py`. Results follow new information but are never silently rewritten:
- **Rechecks** (`consent_recheck`, every minute, 1,000 contacts a turn, resumable): a new proof or a proof's date
  changing (`new_proof` / `certificate_read`), a late STOP (`late_opt_out`, from its time), a new owner
  (`owner_changed`, from the split; proofs move to the owner of their date), an approved rule update or a changed
  Rulebook file (`rule_changed`, signal `apps.rulebook.signals.rules_changed`, from its start date). Pending results
  whose certificate was read are checked again every minute; certificates expiring within the warning days, nightly
  at 03:00 (`time_passed`). Each result keeps `reeval_reason`.
- **History** (`consent_result_change`, locked): every change of status or code, and every freeze, with its reason.
- **Freezing:** a checked call whose record comes back with different facts (time, number, channel, direction, dial
  mode, lead ID) → `FZ_INPUTS_CHANGED`; a proof whose record no longer gives it, or gives another date → withdrawn and
  results that used it frozen; the weekly full check (`SyncCursor.sweep_started_at`, `handoff.SEEN` /
  `handoff.SWEEP_DONE`) not finding a call or proof record → `FZ_SOURCE_DELETED`. Frozen results are never checked
  again and are left out of totals; withdrawn proofs are never used again.

### Consent results in the portal (Module 6, step 5)

Strict results only. `GET /api/contacts` gives each row's status, primary code, reason in words, the five checks
(`pass` / `fails` / `gap` / `not_reached` / `not_measured`), bases and proof; `?status=` filters by result
(`NOT_CHECKED` = no result yet). `GET /api/evidence/<ref>` adds the number's standing (worst counted contact; pending,
frozen and not needed left out), counts, real opt-outs and a `consent` block (`apps/consent/panel.py`: the current
owner's proofs, what the latest contact needed, the last 20 changes, frozen and pending counts, not-measured checks,
draft rules). `GET /api/consent` (`apps/consent/api.py`): this month's mix, top reasons, legal basis share, DNC list
not supplied share, certificate validity, before-engagement expiries, four-month trend, certificates expiring within
7 / 30 / 90 days, and pending / frozen / not needed apart. `GET /api/certificates`: the client's certificate claims
(first 8 characters of the ID only), state, dates, page, and how many contacts' results used each. Words in
`apps/consent/words.py`.

## Certificates: where from, who holds them, fingerprint-only proof (Module 7, step 1)

- **Where from** (`apps/consent/sources.py`, owner decision): each proof keeps the record's own word for how it was
  made (`source_hint`: HubSpot `hs_object_source`, Salesforce `LeadSource`). `source_of()` → **client_form** (HubSpot
  FORM; a Salesforce "Web" lead not part of an upload or feed), **vendor** (HubSpot INTEGRATION/API, or an automatic
  feed), **uploaded_list** (HubSpot IMPORT, or a Module 5 upload batch), else **unknown**. Never skips a check.
- **Who holds it** (`custody_of`): CiV claims every certificate automatically in the client's own account (no switch;
  covered by the service agreement) → claimed / being claimed / not claimed in time / provider does not have it.
  A vendor-only holder cannot be seen through the API (to confirm on a real account): never guessed.
- **Fingerprint-only proof:** a claimed certificate past its expiry date (or found gone) no longer opens; CiV read it
  and holds its sealed fingerprint → **WK_FINGERPRINT_ONLY** (weak), not conflicting. Nightly, `mark_gone()` sets
  `CertificateClaim.gone_at` from the expiry date the provider gave at claim time (no extra request, no extra cost)
  and queues rechecks of the numbers that used it.

### Phone match (Module 7, step 2)

Owner decision A: phone numbers are never stored, so the match happens **while the lead is being read**. The
certificate scanner (`scan_record` → `match_phones`) takes each phone of a CRM lead or person record that carries a
certificate and, in the same request as the claim, asks TrustedForm whether it was typed into the form
(`match_lead`, `vendors.claim_trustedform(..., phone)`; an already claimed certificate gets a match-only request).
Only the answer is kept: `CertificateClaim.phone_match` = {phone code: true/false}. A "no" →
**CF_PHONE_MISMATCH** (conflicting); a "yes" removes `not_measured:phone_match`; no answer (provider down, dialer
record, Jornaya) stays "not measured" and never makes a result worse. A new answer queues a recheck of that number.
Lead matching's request and answer shape are built from TrustedForm's docs and marked **to confirm**; Jornaya's
matching is to confirm.

### CiV's own copy of each consent page (Module 7, step 3)

`apps/captures` (spec `page_capture`; decision D32a: CiV keeps the screenshot, the page text and the measurements).
- **Pages:** every page named by a claimed certificate (host and path only, never the "?" part) becomes a
  `consent_page`, once per client and address. Pages named in the last 30 days are captured about once a day
  (`page_capture_interval_hours`), at phone and computer size (`cc_viewports`: 390×844, 1440×900).
- **A capture** (`page_capture`): screenshot (private media file), the page's words, the consent block's words (the
  element with the most permission words, if any on that page), measurements for Step 4 (checkboxes and whether
  ticked, buttons, the consent block's font size, colours and position, phone fields), hashes, and a sealed
  fingerprint (grade A, captured by CiV itself). A page that does not open is recorded with the reason, never held
  against the client. The browser never types into or submits a form.
- **Safety:** only public internet addresses on ports 80/443 are opened; every request the page makes is checked the
  same way; a redirect to a private address keeps nothing; service workers are blocked.
- **Where it runs:** its own container `capture` (`deploy/Dockerfile.capture`: Debian Chromium, `CHROMIUM_PATH`),
  Celery queue `capture`, hourly (`capture_pages`); the main worker never opens a browser. Locally, Playwright with
  `CHROMIUM_PATH=/usr/bin/chromium`.
- **Kept 4 years** (owner decision: the TCPA time limit to sue): nightly `purge_old_captures` deletes older
  screenshots and words; hashes and fingerprints stay.

### The consent checklist (Module 7, step 4)

`apps/captures/checklist.py` reads CiV's capture of a certificate's page taken within `page_snapshot_max_gap_days`
(1) of the consent, closest first; no capture that close → `not_measured:consent_wording`, never worse.
Rule items per screen size, the worse counting (owner decision): **CC_CONSENT_TEXT** (no permission words although the
page has a phone box and a button → **NP_NO_CONSENT_TEXT**; no phone box → not measured, the form may go on later),
**CC_UNTICKED** (a ticked box next to the words → **NP_PRETICKED**), **CC_BUTTON_MATCH** ("by clicking X" names a real
button), **CC_NUMBER_SHOWN**, **CC_FONT_SIZE** (`cc_min_font_px`, draft 10 px), **CC_CONTRAST** (`cc_min_contrast_ratio`
4.5 : 1, 3 : 1 from 24 px) → any failing = **WK_WORDING**; **CC_ABOVE_BUTTON**, **CC_NO_SCROLL** = warnings only;
**CC_SELLER_NAMED** (the client's own name; no brand list) = information only. Meaning items (opt-out, not a
condition, autodialer disclosed) wait for AI (`not_measured:ai_wording`). Results carry `draft:consent_checklist`
while the checklist is not approved. A new capture queues a recheck (`page_captured`) of numbers whose certificate
from that page was made within a day.

**Page match (step 5): skipped** (owner decision 2026-10-21): TrustedForm's copy of the page costs the client per lead;
`not_measured:page_match` stays until a client's plan makes it worth it.

### Made visible (Module 7, step 6)

- `GET /api/consent-pages` (`apps/captures/api.py`): the Wording tab: each page (most common source of its
  certificates, how many certificates), CiV's latest photos, the consent words, and every checklist item with its
  result and effect (no_proof / wording / warning / info / ai). `GET /api/consent-pages/<ref>/photo/<viewport>`: the
  photo, own client only. No approve/reject mark (owner decision: results come only from the checks).
- `GET /api/certificates` adds `source` and `phoneMatch`; the number page's proofs add `source`, `phoneMatch`, `page`.
- **Admin → client page → Consent pages tab** (read only, shown when viewing, left out of a save): each page, when
  seen, the latest photo time or why it could not be captured, Phone / Computer photo buttons (staff only), and the
  checklist.

## Use it with the portal

In the portal repo, put `BACKEND_URL=http://localhost:8000` in `.env.local` and restart `npm run dev`.
The portal then sends sign-in, users, invites, Rulebook, Regulatory Changes, Source Registry and the Overview's Data
health card, Contact Ledger, number pages, "Can I call now?" and the Opt-outs card to Django; other pages use sample data.
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
- The tests log in to the database as a **normal** user (not a superuser), like the server: a superuser skips the
  per-client lock and the "locked per client" tests fail. Python is pinned to 3.14 (`.python-version`), like the server.


## Where each number came from (Module 8, step 1)

`apps/provenance` (spec §5a provenance ladder). Every 30 minutes, per client, for each contacted number and owner:
the latest CRM lead record created at or before the first outbound contact, then the first rung that matches:
1 lead platform feed (no reader yet; built when a client uses one) · 2 **crm_field**: the record names a vendor
(`CrmCreation.vendor`, from any field named for a vendor, provider, publisher, affiliate, supplier, lead source or
utm_source; categories like "Web" or "Organic" ignored; cleaned of case and spaces only) · 3 vendor invoice
(skipped: API only, Document AI later) · 4 **cert_domain**: the website in the number's certificate (own website
when the Module 7 source is the client's form) · 5 **manual_import**: a Module 5 upload batch · 6 **untraced**, with
the reason. `ladder.untraced(client, start, end)` gives the month's untraced list (masked label + CRM record ID) for
the Lead Provenance page. Locked per client.

### Evidence for numbers with no certificate (Module 8, step 2)

`apps/provenance/evidence.py`, called from the proof collector (`apps/consent/proofs.py`) while each record is read;
only the fact, its date and the phone code are kept. **inbound_call**: the person called the client (inbound call
in the dialer or Twilio log) → covers live (not autodialed) calls for 30 days (draft; `inbound_contact_scope`,
counsel B12, is TBD). **inbound_sms**: the whole text is YES, Y, START, UNSTOP or SUBSCRIBE → covers texts.
**form_submission**: the CRM says the record came from the client's web form (HubSpot FORM, a Salesforce "Web"
lead) and it is not part of an upload or feed → covers what any accepted proof covers. None of them is written
consent, so a robocall or a strict-reading marketing text still needs a certificate. Evidence dated after the first
call does not count. Purchases are the Module 6 existing-customer proofs; recordings wait for AI (Module 9).

### More uploads: update uploads and dialer lists (Module 8, step 3)

- **Update uploads** (`CrmUpdate`, `batches.rebuild_updates`): while reading CRM records CiV keeps only a fingerprint
  of their opt-out, do-not-call and lead-source fields (`CrmCreation.watched_sha`, never the values) and whether the
  record is marked opted out. A record that comes back with those fields changed is noted with who changed it
  (Salesforce `LastModifiedById`, HubSpot `hs_updated_by_user_id`) and when; bursts by one user (same gap and size as
  creations; a steady stream is a feed) become `system='crm_update'` batches with `updated_count` and
  `optouts_cleared` (opted-out records the upload un-marked). No client setup (no field history needed).
- **Dialer uploads** (`DialerListEntry`, `dialer_lists.py`, `batches.rebuild_dialer`): Vicidial `vicidial_list`
  (SELECT only, after the last lead ID read; times in America/New_York unless set) and Convoso lead search (built from
  the docs, **to confirm**); Five9 later. Numbers in a dialer list with no CRM record, grouped by list and time added,
  become `system='dialer'` batches. Read before each 15-minute batch rebuild.
- Both count for re-added STOP numbers (M34, `optouts.readded.entries`), for "no evidence found"
  (`batches.origin` falls back to dialer lists), and as the provenance ladder's uploaded-list rung ("Update upload",
  "Dialer upload · list 1002").

### Proof requests (Module 8, step 4)

`apps/provenance/requests.py` (spec §5a). After each 15-minute batch rebuild, every uploaded list not sampled yet gets
a fixed random sample (seeded by the list, so always the same numbers) of called numbers with no evidence: 50, or 100
when the list has over 10,000 records. Lists are keyed by `batch_key` (system | tool | user or list | start), stable
across batch rebuilds. `GET /api/proof-requests`: every list's counts and proof rate, and each request (masked
number, deadline 30 days). Only Admins and the company's lawyer answer: `POST /api/proof-requests/<ref>/answer`
with a file (PDF, picture, sound, email, Word; 25 MB) and its type, or `{"none": true}`.
**Owner decision: CiV keeps the file** (private media, no public address; opened by the company through
`/api/proof-requests/<ref>/file` and by CiV staff in **Admin → Clients → Proof requests**; every opening logged;
deleted after 4 years, fingerprint kept). This departs from the spec's "never store uploaded files": for counsel.
A file makes the number's calls **WK_CLIENT_PROOF_UNCHECKED** (weak) until CiV staff check it in the admin: valid →
a real proof dated the consent date it shows (a signed form counts as signed written consent; a recording or other
document as prior express consent); not valid or "none" → no proof. The proof rate counts only checked-valid
proofs. Document AI (Module 16) will suggest the check later.

### Made visible (Module 8, step 5)

- `GET /api/provenance` (Lead Provenance page): this month's ladder (count and share per rung; `available: false`
  for the lead platform feed and vendor invoices), top named sources, the untraced list, every upload (numbers, with
  evidence, STOP numbers brought back, opt-out marks cleared, proof rate), and the Module 7 checklist items most often
  failing (counted in certificates).
- `GET /api/evidence/<ref>` adds `cameFrom` ("CRM lead source · SolarLeads Inc"); `GET /api/data-health` adds
  `proofRequestsWaiting` for the Overview's attention strip.
- Admin client page: a **Lead provenance** tile (untraced share this month, proof files to check) that opens the
  Proof requests list for that client.

Gate 2 (spec): ready to test in code; passed during the pilot (200 hand-checked contacts, counsel consent items).

**Restored portal features (owner request, 2026-10-21):** consent pages keep the client's own mark
(`ConsentPage.client_mark`, `PATCH /api/consent-pages/<ref>` {mark}; never changes a result), and the page row gives
the vendor the CRM names on its leads, when the consent words last changed on CiV's photos, "checklist X of Y" and
the missing items. Law changes have **Domains it affects** (codes like REV, SMS) next to metrics.

## Card coverage, batch 1 (existing portal cards made real)

`GET /api/access-log` (the company's own access log, CiV staff shown as "CiV team"); `GET /api/contacts/<ce-id>` (one
contact, for the contact panel); ledger rows now carry the real category (`ConsentNeed`), evidence tier (source grade
A→1 … D→4) and record fingerprint; the number page's list checks use the STOP list (DNC scrub records wait for the
Upload centre); `GET /api/vault` (records held, daily seals, last seal, months covered); `GET /api/settings` (company
name, industry, states contacted, engaged since, agreements from client documents); `GET /api/revocation` (Annex C
signed date); `GET /api/insureds/<ref>` (own company: records completeness and the reconciliation table); Source
Registry's "Feeds domains" per kind of tool. The partly real pages (vault, settings, revocation, insureds) send only the
fields they have; the portal fills the rest from its sample until those modules exist.

## Card coverage, batch 2: the Upload centre works

`apps/uploads`. `POST /api/uploads` (multipart: the source's name and the file; Admins and the company's lawyer):
the file is kept write-once in private storage, fingerprinted (SHA-256), deleted after 4 years (fingerprint and rows
kept), and its rows are read with loose column names (`read.py`): **internal do-not-contact list** →
`internal_list_entry` (phone code, date added or the upload day) · **DNC check records** → `dnc_check` (checked on,
listed yes/no, list) · **reassigned-number query logs** → `rnd_query` (yes / no / no data) · **complaint log** →
`complaint` (received, resolved, channel; never the words) · **policies, training, contracts** → `training_record`
(agent ID fingerprinted, trained on) or a kept document (PDF/Word). Rows with no usable phone or date are counted as
not read. `GET /api/uploads` lists the files; Source Registry shows each upload source as current with the last file
and the domains it feeds. Effects: the internal list and DNC checks decide the consent engine's do-not-call need
(`needs.dnc_lists`: on the internal list from its date, or listed in a check within `dnc_check_max_age_days` → dnc
listed; a check that says not listed covers that date → no "DNC list not supplied"); the number page's list checks use
both; numbers in a new file are checked again.

## Card coverage, batch 3: Contact Conduct

`apps/metrics` (Module 10's app, started here). `GET /api/conduct` (fully real: outside-hours by state, "possible"
count, contacts by the person's local hour, abandoned rate by campaign and the limit) and `GET /api/metrics?period=`
(only the metrics that are real so far; the portal keeps the sample for the rest, merged by metric code). From the
contacts CiV holds, over the chosen month or the last 30 days: **M16** out of hours (federal · state, each contact
counted once; several possible time zones or low confidence = "possible"), **M17** over a state's frequency limit
(per number and owner, campaigns together), **M19** robo contacts without the proof they need (strict), **M15**
cross-border, **M31** abandoned rate from dialer result codes (rough until each dialer's codes are mapped). Calling
hours and frequency limits are TBD in the Rulebook: the draft values are used and every number says so. **M18**
(holiday rules have no draft) = "rule pending"; **M21** pass rate waits for CiV's test dials (Module 9), its STIR/SHAKEN
mix is shown when the dialer gives it. Each metric carries a four-month history.

## Card coverage, batch 4: Who You Contact

`GET /api/who-contact` (`apps/metrics/who.py`, last 30 days) sends the checks that are real now, with the portal's own
check names so each replaces its own row (the portal keeps its sample for checks that need a later module): **M40**
expired customer relationship (consent results with `NP_RELATIONSHIP_LAPSED`); with uploaded DNC check records,
**M13** national registry checked (a check within 31 days before the contact), **M39** called after the provider
flagged the number, **M49** registry copy older than 31 days, state lists checked; with the uploaded internal list,
**M12** called after joining it (+ the flagged numbers, masked); **M44** opt-out marks cleared in the CRM; **M47**
consent older than 12 months; with uploaded query logs, **M11** covered by the safe harbor. Services say what was
uploaded. Lead sources are the client's own vendors (CRM vendor names, else certificate websites) and uploaded lists;
`PATCH /api/who-contact/<id>` {column, checked} saves the client's statement (`lead_source_check`, Admins and the
lawyer, logged).

## Card coverage, batch 5: Setup & Readiness, Plan & usage

`GET /api/readiness` (`apps/onboarding/readiness.py`, partly real, merged by check name / setup id): dialer, SMS and CRM
connections (live or not; share of calls with no dial mode), consent proof for up to 100 recent numbers, certificate
retention, consent pages photographed, lead records traced, internal list uploaded, history depth, documents (DNC
check records and query logs uploaded), can the audit start, numbers per month and the recommended plan (Starter to
10,000, Growth to 50,000, Scale to 250,000, then Enterprise), a preview of consent results on those numbers, and the
setup rows CiV can count (caller IDs, pages, vendors, campaigns — all treated as marketing — and states). Recordings
wait for Module 9. `GET /api/settings` adds `usage`: plan, limit, distinct numbers contacted this month and the three
before, months over the limit in a row, next plan, monthly price from the contract. `GET /api/billed-numbers`: this
month's billed numbers as a CSV of masked labels (never the number), first contact and contacts.

## Card coverage, batch 6: Overview, Lead Provenance, Vendor Ledger, top bar

`/api/metrics` adds **M01** consent coverage (legal-basis contacts verified or weak; overall share in the note) and
**M10** contacts after opt-out (strict results with `NP_AFTER_OPT_OUT`), each with a four-month history.
`GET /api/leads` (merged): leads this month (CRM records created), consent completeness (leads whose form page passed
every rule checklist item, among leads with a photographed page), the checklist items most often missing; signal
levels and page match keep the sample (paid certificate data). `GET /api/vendors` (merged): the client's own vendors
and their leads this month, "not enough data" until Module 12 (empty → nothing sent, the page keeps its rows).
`GET /api/search`: numbers (last 4 digits or a full number, answered masked) and vendors; the portal adds pages,
domains and metrics. The session's `updatedAt` is the last time CiV read something new. The month list stays the
sample's until Module 10 (the score pages read it).

## Card coverage, batch 7: proof elements, position lookup, hash check, Rulebook snapshot, attestation

The number page's **eight proof elements** (`apps/contacts/proof_elements.py`, current owner): every contact
verified or weak; consent page photo (Module 7); third-party certificate claimed; lead source (Module 8 ladder);
contact log fingerprint; opt-out history (a STOP's record, or a connected texting tool); internal list uploaded;
the client's own reassigned check (uploaded logs). Each with its tier, time and fingerprint; "not measured" when
nothing can say. `GET /api/position?phone=&date=` (the Vault's lookup: owner, proof, page, lead source, last contact,
opt-out history, internal list and consent status as of the end of that day; the number is never stored) and
`GET /api/hash-check?hash=` (a recorded fingerprint, its record, time, tier and the day's seal).
`GET /api/rulebook/snapshot?period=YYYY-MM`: the rule values in force on the month's last day as a PDF
(`reportlab`); the Reports card downloads it. `GET /api/insureds/<ref>` adds the attestation rows the records answer
(contacts per month, prerecorded share when the dialer says, purchased-lead and manual-import shares, evidence found,
consent proof rate, contacts after opt-out, re-added numbers, internal-list contacts, monitoring, records
fingerprinted); the rest keep the sample and its worst-case notes.

## AI conversation review: texts (Module 9, step 1)

`apps/conversations` (spec §8, D37). Every minute: numbers where the customer wrote and the thread has been quiet for
10 minutes, with a message newer than the last review. The thread (last 30 days) is re-read **by message ID from the
tool, in memory only** — one small reader per tool (`readers.READERS`, Twilio now; a new texting connector adds its
reader), everything else shared — and sent to the **AI slot** (`ai.py`). **No AI is chosen yet (owner decision): the
slot is off, nothing is sent anywhere and nothing is saved**; `CONVERSATION_REVIEW_MODEL` + the chosen AI's adapter
switch it on. Results (`conversation_review`, locked): opted_out / wrong_number → the STOP list (`method='ai'`;
wrong number also starts a new owner) · opted_back_in → the earlier opt-out's `lifted_at` (the consent engine
ignores it from then) · partial_request → kept for the client · unclear (below 90 % sure) / none → counted ·
not_reviewed when the tool can't share the words. Kept: result, deciding message, confidence, AI and prompt version,
fingerprint of the words. Never the words or the number.

### Calls (step 2)

**Every** recorded call is listened to (owner decision: no skipping short calls), once it ended (10 min after start)
and within 30 days. The recording is fetched from the dialer in memory — one reader per dialer
(`readers.RECORDINGS`: Twilio recordings by CallSid, Vicidial `recording_log`, Convoso call-log link *to confirm*;
Five9 and others "not reviewed" until their reader is added) — turned into words by the **speech-to-text slot**
(`speech.py`, customer and agent told apart; off until chosen), then the **same AI request** as texts ("one listen,
one request, several answers": later questions such as disclosures go in this request). The moment is the second in
the call (`moment_seconds`, `moment_at` = call start + seconds). A stop said by the agent, or with no deciding moment,
is "unclear". No recording → not_reviewed "No recording". The recording and words are dropped at once; only the
result and a fingerprint stay. Recording consent (C22) is noted for the client's lawyers.

### Did the tools mark the stop? (step 3)

`apps/optouts/marks.py`, every 5 minutes. For each opt-out on the STOP list (not lifted), one `MarkCheck` per connected
dialer, texting tool and CRM: was the number marked "do not contact"? One small check per tool (`marks.CHECKS`):
Vicidial re-reads the number from its own call record (in memory, checked against the phone code) and looks in
`vicidial_dnc` / `vicidial_campaign_dnc` (SELECT only) · Convoso DNC search (*to confirm*) · Twilio blocks stop words
itself (plain-word opt-outs can't be checked) · CRMs use the synced opt-out / do-not-call field (no extra calls) ·
Five9 later. A tool that can't tell = `marked: null` "not checked", **never a fail**. Timing: first check 10 minutes
after CiV learned of the opt-out; not marked → **urgent** (`urgent_at`, shown in the portal in step 6; **no email**,
owner decision). Then again every hour until the deadline; marked → once more a day later (marked then unmarked →
urgent). Still not marked at the deadline → `missed` = **M38 Missed opt-outs** (`missed_optouts`). Opt-outs older than
a day when first seen are checked but raise no urgent alert.

### The AI's exam (step 4)

`apps/conversations/exam.py`. Made-up conversations with known answers: `exam/text.json` and `exam/call.json` (300
each — stops, wrong numbers, "allowed again", limits, and tricky "none" cases such as an agent saying "stop", "stop by
tomorrow", other languages) plus `ExamCase` rows CiV staff add. Marked through the same `judge()` as live reviews.
**Pass = every stop caught (100 %, with the right moment) and ≥ 98 % of all answers right**, texts and calls separately
(owner decision 2026-10-21; Rulebook `conv_review_stop_catch_mark`, `conv_review_accuracy_pass_mark`). Runs daily at
02:10 when the AI or `PROMPT_VERSION` changed or 30 days passed (calls only once speech-to-text is chosen); each run
sends about 300 conversations per channel to the AI. Below 90 % sure, a possible stop is treated as a stop.

Until the AI passes (`ConversationReview.trusted`): its stops still go on the STOP list and are still checked in the
tools, but `OptOutEvent.counts = False`, so they don't count against the client (consent engine, M10, M38). "Allowed
contact again" and the new owner after "wrong number" wait (`approval = waiting`). Admin → **AI**: *AI answers*
(approve / reject / report as wrong; *Read* re-reads the conversation from the client's tool for one look, never
saved, logged), *AI exam results* (red "AI failed the exam" with the mistakes), *Extra exam questions*. Reporting a
wrong answer fails the AI at once; a wrong stop stays on the STOP list but stops counting, a wrong "allowed again" is
undone.
Each client's admin page has an **AI review** tile in the top row: stops found this month, conversations read, answers
waiting for staff, and the exam state for texts and calls; it opens *AI answers* filtered to that client.

### M08 and M09 from real opt-outs (step 5)

Owner decision 2026-10-21: **no paid CiV test lines**. `apps/optouts/measures.py` measures from the client's real
opt-outs instead (only those that count), using the step 3 tool checks, labelled "Measured from your real opt-outs"
(Tier 3). **M08** opt-out propagation time: hours from the opt-out until every checkable tool had marked the number —
median and 90th percentile, "NEVER" when a tool still hadn't by the deadline (accurate to about an hour: CiV checks
after 10 minutes, then hourly). **M09** opt-outs past their deadline: **M09a** not marked in a tool · **M09b**
contacted after the deadline. Not measured until there is data. Shown in the portal in step 6.

### In the portal (step 6)

- `GET /api/revocation`: M08 median / 90th percentile, M09a / M09b, the opt-out matrix (rows: STOP texts, plain-word
  texts, spoken on a call, CRM box; columns: the client's tools; median hours per cell, NEVER when missed) and the
  time-to-stop chart, last 90 days. Before anything is checked the KPIs say "Not measured" and the matrix keeps its sample.
- `GET /api/optouts`: `dialerMarked` (dialers only), plus `tools` (each tool's answer), `urgent`, `counted`.
- `GET /api/data-health` → `conversationReview` (Overview card "Opt-outs your dialer missed"), last 30 days.
- `GET /api/metrics`: M08 and M09 added.
- Who You Contact: **M41** stop requests that never reached every tool, **M42** share marked within the deadline,
  **M48** contacts after a "wrong number" reply, **M45** contacts after naming an attorney (a 4th answer in the same AI
  request, `ConversationReview.attorney_at`; trusted reviews only; complaint-log demand letters not counted yet). Shown
  once the AI has read anything; before that the sample rows stay.
