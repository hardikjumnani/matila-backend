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