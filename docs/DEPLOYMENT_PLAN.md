# Azure Deployment & Production Validation Plan

Runbook to take the backend from a validated local environment to production on
Azure. Execute phase-by-phase; **do not proceed until a phase's success gate is
met.** Guided, one step at a time (like the local onboarding).

---

## Current state (validated locally — see LOCAL_SETUP_LOG.md)
Postgres 16, Redis, Django + Daphne, Celery worker + beat, WebSockets/channel
layer, **Firebase Auth (live)**, **Azure Blob Storage (live)** — all working.
**Deferred:** Razorpay live + webhook (lands in Phase H with a real HTTPS URL).

## Target Azure architecture
| Concern | Service |
|---|---|
| Compute | **Azure VM**, Ubuntu 22.04 LTS, 2 vCPU / 4 GB (e.g. B2s). Runs Gunicorn (REST), Daphne (WS), Celery worker, Celery beat, Nginx. |
| Database | **Azure Database for PostgreSQL — Flexible Server** (private access) |
| Cache / broker / channels | **Azure Cache for Redis** (Basic C0/C1 for MVP) |
| Object storage | **Azure Blob Storage** (done) — a dedicated prod account/container |
| TLS / reverse proxy | **Nginx + Let's Encrypt** (certbot), `wss://` for WebSockets |
| Secrets | `/etc/matila/env.production` (`0600`) — optionally Azure Key Vault later |
| Errors / monitoring | **Sentry** + request-ID correlation + Azure Monitor |

VM chosen over App Service/Container Apps because we run four long-lived
processes (Gunicorn, Daphne, Celery worker, **Celery beat**); a VM + systemd is
the simplest reliable fit for that shape at MVP scale.

---

## Pre-deployment code milestone (do first, locally)
**Request-ID correlation** (approved refinement): a middleware that generates/
accepts an `X-Request-ID`, binds it to the logging context, propagates it to
Celery tasks and WebSocket connections, and stamps `AuditLog.request_id` — so a
single request is traceable end-to-end (REST → task → audit → Sentry). Implement
and test locally before deploying. **Gate:** request id appears in logs, audit
records, and Sentry events for a traced request; suite still green.

---

## Phase A — Provision Azure resources
**Objective:** Stand up compute, database, cache, and networking.
**Deliverables:** Resource group `matila-prod-rg`; VM (Ubuntu 22.04, public IP,
SSH key, NSG allowing 22/80/443 only); PostgreSQL Flexible Server (private);
Azure Cache for Redis; a prod Blob account + `media` container; a DNS name.
**Validation:** SSH into the VM; from the VM, `psql` connects to Postgres and
`redis-cli`/`PING` reaches Redis over the private network; Postgres/Redis are
**not** reachable from the public internet.
**Gate:** all resources deployed; DB + cache reachable **only** privately from
the VM; SSH works.

## Phase B — Deploy the application
**Objective:** Run the four processes under systemd on the VM.
**Deliverables:** OS deps (python3.11, venv, build tools); repo cloned; venv +
`requirements/production.txt`; `/etc/matila/env.production` (`0600`, real
secrets, `DJANGO_SETTINGS_MODULE=config.settings.production`); `migrate`;
`collectstatic`; systemd units for `gunicorn`, `daphne`, `celery-worker`,
`celery-beat`.
**Validation:** `manage.py check --deploy` clean; all four services active +
auto-restart; `GET /health/` via Gunicorn = 200; `celery inspect ping` +
scheduled tasks listed; a WebSocket connects through Daphne.
**Gate:** four services active & restarting; health green; worker + beat live.

## Phase C — Nginx, TLS, `wss://`, log hygiene
**Objective:** Terminate TLS; proxy HTTP + WebSocket; prevent token leakage.
**Deliverables:** Nginx site (`/` → Gunicorn, `/ws/` → Daphne with Upgrade
headers); Let's Encrypt cert + auto-renew; `SECURE_PROXY_SSL_HEADER` wired; an
access-log format that **strips the `?token=` query string**.
**Validation:** HTTPS works, HTTP→HTTPS redirect, HSTS present, SSL Labs ≥ A;
`wss://…/ws/chat/{id}/?token=…` connects; **grep access logs for a known token →
zero hits**; `certbot renew --dry-run` succeeds.
**Gate:** HTTPS + wss working; no token in any access log; cert renewal verified.

## Phase D — Runtime configuration seeding
**Objective:** Seed `app_config`/`feature_flags`; set the admin allow-list.
**Deliverables:** idempotent seed (prices, gesture pool, questionnaire, versions,
support info) via admin API/command; `ADMIN_EMAILS` set; feature flags set.
**Validation:** `GET /config` returns intended launch values; an `ADMIN_EMAILS`
user reaches `/admin/dashboard/stats` (200), a non-admin gets 403; toggling a
flag reflects live.
**Gate:** `/config` matches launch intent; admin access correct; flags toggle.

## Phase E — Observability
**Objective:** Errors, logs, and health visible before real users.
**Deliverables:** `sentry-sdk` (in `requirements/production.txt`) initialized in
`production.py` (DSN from env, PII scrubbing, Django+Celery integration);
request-ID correlation live; Azure Monitor/Log Analytics + uptime check on
`/health/`; alerts (API uptime, error rate, DB connections, Redis memory, Celery
backlog, WS disconnects, webhook success).
**Validation:** a deliberate error appears in Sentry **with the request id and no
secrets**; stopping Gunicorn fires the uptime alert; queue depth + Redis memory
visible on a dashboard.
**Gate:** Sentry capturing (PII-scrubbed, correlated); uptime alert fires; core
metrics dashboarded with thresholds.

## Phase F — Backups & disaster recovery
**Objective:** Prove data is recoverable, not just backed up.
**Deliverables:** confirm Azure PostgreSQL Flexible Server automated backups +
point-in-time-restore retention (≥7 days); documented restore procedure; note
that Redis is ephemeral by design (no backup needed).
**Validation:** perform a **PITR to a new server**, run `migrate --check` + a read
query → data intact.
**Gate:** a restore **succeeded** end-to-end (backup existence alone is not
sufficient).

## Phase G — End-to-end validation + load test
**Objective:** Exercise the full frozen journey on prod infra, then a light load
test before real users.
**Deliverables:** scripted E2E (auth → onboarding → verification → admin approve
→ match → anonymous chat over REST + live WS → reveal eligibility → mutual
reveal + sandbox pay → REVEALED → expiry/extension → report → rating); a
**~100-concurrent-user load test** (join matchmaking, exchange messages, hold
WebSocket connections) via Locust/k6.
**Validation:** every frozen step works on prod infra; background jobs fire on
schedule; under ~100 concurrent users, error rate ≈ 0, WS stays connected, DB/
Redis/Celery healthy, no Sentry errors.
**Gate:** full journey passes on prod; load test sustains ~100 users within
acceptable latency/error thresholds.

## Phase H — Razorpay live, webhook, go-live & rollback
**Objective:** Finish the deferred payment integration and cut over safely.
**Deliverables:** Razorpay live (or sandbox-then-live) keys + a **webhook** to
the real HTTPS URL; deploy script (pull → migrate → collectstatic → restart);
documented rollback (previous release + DB restore point).
**Validation:** webhook signature verified against a real Razorpay call
(idempotent with client-verify); one controlled low-value live transaction;
rehearse rollback on a staging copy.
**Gate:** live payment + webhook verified; rollback rehearsed; monitoring quiet.

---

## Dependencies this plan adds
- `sentry-sdk` → `requirements/production.txt` (Phase E). Official, integrates
  with Django + Celery; named in the monitoring checklist.
