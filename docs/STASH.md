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

### 2. Complete Google Play Billing go-live setup
- **What:** Payments switched **Razorpay → Google Play Billing** (reveal/extension
  are *digital in-app purchases* → Play policy requires Play Billing; also unblocks
  the slow Razorpay activation review). **Backend implemented + unit-tested**:
  `POST /api/v1/payments/verify-purchase {chat_id, purpose, product_id,
  purchase_token}` verifies the token via the Play Developer API (`gateway_play`)
  and drives the **same** reveal/extension completion. Razorpay code is **parked**
  behind `PAYMENT_PROVIDER` (default `google_play`) for web/other platforms later.
- **Pending (Play Console / Google Cloud — mostly non-code):** create the two
  **consumable** products (`reveal_unlock` ₹59, `chat_extension` ₹89, IDs in
  `apps/payments/constants.py`); a **service account** with Android Publisher API
  access → JSON key on the VM (`0600`) at `GOOGLE_PLAY_SERVICE_ACCOUNT_PATH`; set
  `GOOGLE_PLAY_PACKAGE_NAME`; app on an **internal test track** + license testers.
- **Do later** (go-live): finish the above + set the env, restart, run a real
  **test purchase** (license tester) end-to-end → `verify-purchase` →
  REVEALED/EXTENDED, then flip `payments_enabled`/`reveal_enabled` on. FE side is
  tracked via the switch prompt handed to the frontend agent. **Until live: keep
  the payment flags OFF for real users.**

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

### 7. Google Play refund / void reconciliation
- **What:** the backend verifies purchases on demand but doesn't yet handle
  **refunds/chargebacks** (revoke a reveal/extension after Play refunds it).
- **Why deferred:** the verify path covers MVP; refunds are rare and reconcilable
  later. (Reveal is a permanent state anyway — a refund would mostly matter for
  ledger accuracy / abuse.)
- **Do later:** subscribe to Play **Real-time Developer Notifications** (Cloud
  Pub/Sub) for voided-purchase / one-time-product events → mark the `Payment`
  REFUNDED (+ revoke where applicable); or poll the **Voided Purchases API**.

---

## Done

- **Production WebSocket `Origin` policy** (2026-08-19, Phase G step 0) — prod's
  `AllowedHostsOriginValidator` was 403-ing the native no-`Origin` socket. Replaced
  it with `apps/common/ws_origin.py::MobileFriendlyOriginValidator`: no-`Origin`
  (native) sockets pass through to the Firebase token gate; browser origins are
  still checked against `ALLOWED_HOSTS`. Verified live (evil origin → 403; no-origin
  reaches FirebaseAuth). Native app needs no change.
