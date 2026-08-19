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

### 2. Swap Razorpay TEST → LIVE keys at go-live
- **What:** Phase H wires **test-mode** keys (`rzp_test_…`) + a test webhook and
  validates the full payment→reveal/extension flow in sandbox on prod. Live keys
  are blocked because the Razorpay account is **in activation review**.
- **Why deferred:** only Live keys are gated by the review; test keys work now, so
  the integration is built + proven and go-live becomes a key swap.
- **Do later** (when Razorpay activation clears): in `/etc/matila/env.production`
  replace the `rzp_test_…` key/secret with the **live** `rzp_live_…` pair;
  **re-register the webhook in Live mode** (same URL `…/api/v1/payments/webhook`)
  and update `RAZORPAY_WEBHOOK_SECRET`; restart services; run **one controlled
  low-value LIVE transaction** end-to-end; confirm monitoring quiet. Only then is
  the app safe to expose to real paying users. (Until then, if the client is
  pointed at prod, keep `payments_enabled`/`reveal_enabled` OFF for real users —
  test-mode payments must never reach real users.)

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

### 6. Scale beyond ~100 concurrent users
- **What:** Phase G load testing proved the 1 GB `B2ats_v2` handles **~100 concurrent
  users comfortably** (100% success, ack-RTT p95 109 ms). At **1000** it collapses —
  the first hard limit is **Postgres `max_connections=30`** (join/message writes get
  "remaining connection slots reserved…"), then the single Daphne process saturates
  (nginx 502s) and the box swaps.
- **Why deferred:** ~100 concurrent is ample for an MVP launch; scaling is a
  when-usage-grows problem, and bigger compute costs (against the $100 runway).
- **Do later** (when concurrency demands it), in rough order of value: add
  **PgBouncer** (pool app→PG connections so `max_connections` isn't the ceiling);
  raise `max_connections` (needs more RAM); run **multiple Daphne workers**; move to
  a **larger VM** or managed Postgres. Re-run `ops/loadtest/` to find the new ceiling.

- **Minor:** a WebSocket handshake to a **malformed (non-UUID) `chat_id`** returned
  HTTP 500 instead of a clean 4004 close (only reachable with a bad client; the app
  never sends one). Harden the consumer/route if convenient.

---

## Done

- **Production WebSocket `Origin` policy** (2026-08-19, Phase G step 0) — prod's
  `AllowedHostsOriginValidator` was 403-ing the native no-`Origin` socket. Replaced
  it with `apps/common/ws_origin.py::MobileFriendlyOriginValidator`: no-`Origin`
  (native) sockets pass through to the Firebase token gate; browser origins are
  still checked against `ALLOWED_HOSTS`. Verified live (evil origin → 403; no-origin
  reaches FirebaseAuth). Native app needs no change.
