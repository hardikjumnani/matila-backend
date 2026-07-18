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