# STASH — Deferred Work

A running log of things we've **consciously decided to do later**, so they don't
get lost. Add an entry whenever the owner says "stash this" / "we'll do this
later." Keep each entry short: **what**, **why deferred**, and **when/where** it
gets picked up. When an item is handled, move it to *Done* (or delete it).

> This is a parking lot, not the plan. The live plan is `docs/ROADMAP.md` +
> `docs/DEPLOYMENT_PLAN.md`; provisioning history is `docs/AZURE_PROVISION_LOG.md`.

---

## Open

### 1. Harden / remove Django's built-in `/admin/`
- **What:** `django.contrib.admin` is mounted at `/admin/` (`config/urls.py`) and
  is publicly reachable over HTTPS. It's a **separate** system from the app's real
  admin (the `/api/v1/admin/…` JSON API gated by `ADMIN_EMAILS` + Firebase). No
  Django superuser exists, so nobody can actually log in — but it's an unnecessary
  public brute-force surface.
- **Why deferred:** low risk today (no superuser); the real admin path is the JSON
  API, so this is cleanup, not a blocker.
- **Do later** (Phase C/E hardening): either restrict `/admin/` to the owner IP in
  Nginx, or drop the route from `config/urls.py` entirely. Decide first whether
  Django admin is ever wanted; if not, remove it outright.

### 2. Razorpay live keys + webhook (Phase H)
- **What:** prod `/etc/matila/env.production` currently holds **placeholder**
  Razorpay values (`RAZORPAY_KEY_ID=rzp_placeholder_phase_h`,
  `KEY_SECRET`/`WEBHOOK_SECRET=placeholder_phase_h`), and the `payments_enabled` /
  `reveal_enabled` feature flags are seeded **false**.
- **Why deferred:** real keys + a webhook need the live HTTPS URL (now available)
  and a controlled go-live — that's Phase H.
- **Do later** (Phase H): drop real Razorpay key/secret/webhook-secret into
  `env.production`, register the webhook at the prod HTTPS webhook URL, flip
  `payments_enabled` + `reveal_enabled` to **true**, run one controlled low-value
  live transaction, and rehearse rollback.

### 4. Upgrade prod Python to 3.11+ (before 2026-10-04)
- **What:** prod runs **Python 3.10.12** (matches the Ubuntu 22.04 system Python).
  `google.api_core` (a `firebase-admin` dependency) warns it will stop shipping
  updates for Python 3.10 after **2026-10-04**.
- **Why deferred:** 3.10 works fine today; this is about future dependency updates,
  not a current breakage.
- **Do later** (before 2026-10-04): install Python 3.11+ on the VM (deadsnakes PPA
  or a newer base image), rebuild `/opt/matila/.venv` on it, reinstall
  `requirements/production.txt`, re-run `check --deploy` + a smoke test, restart
  `matila-asgi` + `matila-celery`. Update the systemd `ExecStart` venv path if it
  changes.

### 5. True point-in-time recovery (WAL archiving) for Postgres
- **What:** current DR is **nightly logical dumps** (`pg_dump` → Blob) — recovery
  point is "last night" (up to ~24 h of writes lost). True PITR needs continuous
  **WAL archiving** (`archive_command` → Blob, + `pg_basebackup`), giving
  any-second recovery.
- **Why deferred:** heavier to run/store on the 1 GB box, and RPO≈24 h is fine
  while there's little/no real user data. Chosen deliberately in Phase F.
- **Do later** (when real users + data justify it): enable WAL archiving to Blob,
  take periodic base backups, and document/test a PITR to a target timestamp.

---

## Done

- **Production WebSocket `Origin` policy** (2026-08-19, Phase G step 0) — prod's
  `AllowedHostsOriginValidator` was 403-ing the native no-`Origin` socket. Replaced
  it with `apps/common/ws_origin.py::MobileFriendlyOriginValidator`: no-`Origin`
  (native) sockets pass through to the Firebase token gate; browser origins are
  still checked against `ALLOWED_HOSTS`. Verified live (evil origin → 403; no-origin
  reaches FirebaseAuth). Native app needs no change.
