# Local Environment Setup Log

Audit trail of every change made to the local development machine while
onboarding the backend for real-infrastructure validation (Step 11). One entry
per guided step. Reversal notes included so any change can be undone.

Machine: Windows 11 Pro. Python 3.10.11 (`C:\Users\User\AppData\Local\Programs\Python\Python310`).

---

## Step 0 — Environment inventory (read-only) — 2026-07-18

**Objective:** Establish a baseline before changing anything.

**Findings:**
- Present: Python 3.10.11 + `py` launcher, git 2.52, Chocolatey, winget, project
  `.venv` (deps installed; suite passing on SQLite).
- Missing: PostgreSQL, Redis, Docker. WSL enabled but no distro installed.
- Nothing listening on 5432 (Postgres) or 6379 (Redis).

**Changes made:** none (inventory only).

---

## Step 1 — Install PostgreSQL 16 — 2026-07-18

**Objective:** Local PostgreSQL 16 service on port 5432 as the production-grade
dev database (replacing the SQLite fallback).

**Command (Administrator PowerShell):**
```powershell
choco install postgresql16 --params "/Password:postgres" -y
```

**Result:**
- Installed **PostgreSQL 16.14** to `C:\Program Files\PostgreSQL\16`.
- Windows service `postgresql-x64-16` = **Running / Automatic**.
- Superuser `postgres`, password `postgres`, port `5432`.
- Verified: `psql -U postgres -c "SELECT version();"` → `PostgreSQL 16.14`.
- Chocolatey added `C:\Program Files\PostgreSQL\16\bin` to PATH (needs a new
  shell / `refreshenv` to take effect).
- Side effect: `vcredist140` was installed and requested a reboot (exit 3010).
  Non-blocking; reboot recommended at a convenient time.

**Reversal:** `choco uninstall postgresql16` (and optionally delete the data
directory).

---

## Step 2 — Create the project database — 2026-07-18

**Objective:** Create the `anonymous_chat` database the backend connects to.

**Command:**
```powershell
psql -U postgres -c "CREATE DATABASE anonymous_chat;"
```

**Result:** Database `anonymous_chat` (owner `postgres`, UTF8) created and
verified via `psql -U postgres -lqt`.

**Reversal:** `psql -U postgres -c "DROP DATABASE anonymous_chat;"`

---

## Step 3 — Install Redis (Memurai) — 2026-07-18

**Objective:** Redis-compatible server on port 6379 for cache, Celery broker,
and the Channels layer.

**Command (Administrator PowerShell):**
```powershell
choco install memurai-developer -y
```

**Result:** Memurai Developer installed; Windows service `Memurai` =
**Running / Automatic** on port 6379. Verified `memurai-cli ping` → `PONG`.
Memurai is a native-Windows, Redis-protocol-compatible server (chosen because
Redis has no official Windows build and Docker/WSL are not installed).

**Reversal:** `choco uninstall memurai-developer`.

---

## Step 4 — Wire project to Postgres/Redis + migrate — 2026-07-18

**Objective:** Make PostgreSQL the default development database; connect Django
to local Postgres + Redis; create all tables.

**Machine/config changes:**
- Local `.env` (git-ignored): added `DATABASE_URL=postgres://postgres:postgres@localhost:5432/anonymous_chat`
  and `REDIS_URL=redis://localhost:6379/0`.
- Repo `config/settings/development.py`: PostgreSQL is now the default dev
  database (SQLite fallback removed for development).

**Bug caught by real Postgres (would have failed in production):** the `0002`
migrations that repointed `reviewed_by`/`updated_by` from `auth.User` (int PK)
to `users.User` (uuid PK) issued `ALTER COLUMN … TYPE uuid USING col::uuid`,
which PostgreSQL rejects (`cannot cast type integer to uuid`). SQLite had hidden
this. Fix (safe — greenfield, no deployed data): regenerated
`verification`/`configuration` initial migrations so the FKs are uuid from the
start, and deleted the broken `0002` migrations.

**Result:** `manage.py migrate` applies cleanly on PostgreSQL; no migration
drift.

**Reversal:** revert the settings/migration changes; `DROP DATABASE anonymous_chat`.

---

## Step 5 — Validate the suite on PostgreSQL — 2026-07-18

**Objective:** Close Phase 1's gate — the whole suite passes on Postgres, and
row-level locking is proven.

**Repo changes:**
- `config/settings/test.py`: pin the test cache + channel layer to in-process
  backends so the suite never depends on a running Redis (deterministic,
  CI-identical), while the database still honors `DATABASE_URL` (Postgres
  locally, SQLite in CI).
- New `apps/matchmaking/tests/test_concurrency.py`: two users join
  concurrently, both compatible with one waiting user → asserts exactly one chat
  (validates `SELECT … FOR UPDATE SKIP LOCKED`; skipped on non-Postgres).
- `.github/workflows/ci.yml`: added a `test-postgres` job (Postgres 16 service)
  so this runs continuously.

**Result:** `pytest` → **267 passed on PostgreSQL**; concurrency test green 5/5.

**Changes made to the machine:** none beyond `.env` (Step 4). Everything else is
repo code.

---

## Step 6 — Run the Django backend locally — 2026-07-18

**Objective:** Confirm the app boots and serves against real Postgres + Redis.

**Command:**
```powershell
python manage.py runserver 127.0.0.1:8000
```

**Result:** Server boots on the ASGI/Daphne dev server (Daphne is installed).
Verified `GET /health/` → `{"status":"ok"}` and `GET /api/v1/config` →
`success: true` with pricing/flags/version. `/api/docs/` renders Swagger.

**Notes:** `runserver` serves both HTTP and WebSocket in dev (Daphne). Gunicorn
is Linux-only and is not used on Windows — it is a production concern for the
Azure phase. No machine changes.

---

## Step 7 — Run Celery worker + beat — 2026-07-18

**Objective:** Validate background jobs against the real Redis broker.

**Commands:**
```powershell
python -m celery -A config worker -l info --pool=solo   # Terminal A
python -m celery -A config beat -l info                 # Terminal B
```

**Result:** Worker connected to `redis://localhost:6379/0`, printed
`celery@MegaFunBox ready.`, and registered all 5 tasks. An on-demand
`refresh_configuration_cache.delay()` was **received → succeeded**. Beat ticks
on schedule. (Windows requires `--pool=solo`; default prefork pool unsupported.)

**No machine changes.**

---

## Step 8 — Validate the real Redis channel layer — 2026-07-18

**Objective:** Prove WebSocket fan-out works through Memurai.

**Action:** Ran a `get_channel_layer()` probe (`group_add` → `group_send` →
`receive`) against the RedisChannelLayer.

**Result:** Round-trip succeeded — message delivered through Memurai. Confirms
the production channel-layer path works on real Redis. (Full *authenticated*
WebSocket round-trip is deferred until Firebase auth is configured.)

**No machine changes.**

---

## Step 9 — Firebase Authentication (local) — 2026-07-19

**Objective:** Configure Firebase and validate the auth chain end-to-end.

**Actions:**
- Created Firebase project `matila-dev`; downloaded a service-account key to
  `C:/Users/MegaFunBox/secrets/matila-dev-firebase-adminsdk-fbsvc-c69892faee.json`
  (kept outside the repo; secret).
- `.env`: `FIREBASE_CREDENTIALS_PATH` set; production sign-in method decided =
  **college email OTP, passwordless** (no Google sign-in).
- Minted a real Firebase ID token via the Admin SDK custom-token flow (no
  password provider enabled), verified it, and ran `bootstrap_session` → created
  a real user in Postgres with `next_action=COMPLETE_ONBOARDING`.

**Machine finding — clock skew:** the PC clock is ~21s behind and the network
blocks NTP (UDP 123), so `w32tm /resync` reported "no time data available".
Firebase rejected the token as "used too early". Fix: added a configurable
`FIREBASE_TOKEN_CLOCK_SKEW_SECONDS` (default 10 for prod) to token verification;
set to `60` locally to absorb the offset. (Recommend fixing the machine clock
when NTP is reachable.)

**Repo code changes:** `apps/common/firebase.py` (clock-skew tolerance),
`config/settings/base.py` (new setting), `.env.example` (doc).

---

## Step 10 — Storage switched to Azure Blob — 2026-07-19

**Objective:** Standardize object storage on Azure Blob (deploying on Azure);
drop AWS S3.

**Env change:** `pip install azure-storage-blob==12.24.0` into `.venv` (removed
boto3/django-storages from requirements). **Repo:** `StorageService` rewritten
on the Azure SDK (same public interface); settings AWS_* → AZURE_*; tests
updated.

**Live validation — 2026-07-19:** Created Azure Storage account `matiladevstore`
(RG `matila-dev-rg`, Central India, Standard/LRS) with a **private** `media`
container (Azure-for-Students region policy blocks East US — used an allowed
region). Connection string added to local `.env` (secret; not committed). Ran a
real round-trip: **upload → SAS-URL read (match) → delete → 404 → idempotent
re-delete** — all passed. Quieted the noisy Azure SDK logger to WARNING.

---

## Local runtime environment — COMPLETE

Postgres, Redis (Memurai), venv + deps, migrations, full test suite (267 on
Postgres), Django (runserver/Daphne), Celery worker + beat, and the Redis
channel layer are all working locally. Remaining for full end-to-end:
external integration credentials (Firebase, Razorpay, AWS S3).

---

## Machine migration — new dev box — 2026-08-04

**Context:** The project was moved to a different Windows machine (user profile
`hardi`, repo at `D:\Projects\Matila\Backend`). Inventory of the new box: venv +
deps, the Firebase service-account key (`C:/Users/hardi/secrets/…`, project
`matila-dev`), and PostgreSQL with the **already-migrated** `anonymous_chat` DB
(`migrate --check` clean) all carried over. Dev settings unchanged.

**Only gap:** Redis was absent (nothing on 6379). Reinstalled **Memurai
Developer**; verified service Running, port 6379 listening, `PING → PONG`. This
restores the documented cache + Channels + Celery-broker dependency. Smoke test
after reinstall: `GET /health/` = 200 and `GET /api/v1/config` = 200 (Redis-backed
cache path healthy).

**Reversal:** uninstall Memurai (as Step 3).

---

## Dev tunnel for frontend integration — 2026-08-04 (transient, not a deployment)

To let the frontend engineer run sign-in → onboarding against the real backend
before any Azure deploy, the local server is exposed via a **Cloudflare quick
tunnel** (standalone `cloudflared.exe`, no install, kept outside the repo):

```
python manage.py runserver 127.0.0.1:8000 --noreload      # ASGI/Daphne
cloudflared tunnel --url http://localhost:8000            # → https://<random>.trycloudflare.com
```

Ephemeral by design: the hostname changes on restart and the tunnel is only live
while running on this machine. No repo or persistent machine change (beyond the
Memurai reinstall above). Exposes a `DEBUG=True` dev box with dev-only creds
(dev Firebase, dev Blob; Razorpay not live) — **shut the tunnel down when not
actively testing, and don't share the URL beyond the frontend engineer.** A
stable dev/prod URL + email-link domain lands with the Azure infra phase.

---

## DNS switched to Cloudflare (1.1.1.1) — 2026-08-04

**Symptom:** the Android emulator / host could not resolve the `*.trycloudflare.com`
tunnel hostname — the ISP resolver (via router `192.168.1.1` → `2401:4900:50:9::…`)
returned **NXDOMAIN**, while `1.1.1.1` resolved it correctly. The tunnel + backend
were proven healthy via a DNS-pinned request (`--resolve …:104.16.231.132` →
`GET /health/` = 200), isolating the fault to DNS. Since the emulator inherits the
host resolver, this blocked the live window.

**Change (Administrator PowerShell):**
```powershell
Set-DnsClientServerAddress -InterfaceIndex 9 -ServerAddresses ("1.1.1.1","1.0.0.1","2606:4700:4700::1111","2606:4700:4700::1001")
Clear-DnsClientCache
```
(`InterfaceIndex 9` = the `Wi-Fi` adapter.) Verified: `Resolve-DnsName` returns the
`104.16.x` addresses and `GET https://<tunnel>/health/` = 200 without IP pinning.
Emulator cold-booted afterward to inherit the new resolver.

**Reversal:** `Set-DnsClientServerAddress -InterfaceIndex 9 -ResetServerAddresses`.