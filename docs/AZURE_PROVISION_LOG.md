# Azure Provisioning Log — Production

Audit trail of every Azure resource created for Matila production, with names,
costs, and reversal notes. Region **Central India**. Subscription **Azure for
Students** (`a774bdd0-f2cf-47bb-87bb-eb5bdb7e557d`). Cost-optimized for maximum
$100-credit runway: one free-tier VM runs everything (Postgres + Redis
self-hosted); see `docs/DEPLOYMENT_PLAN.md` / `docs/ROADMAP.md`.

**Reversal (tears down EVERYTHING below):** `az group delete -n matila-prod-rg --yes`

---

## Phase A — Provision (2026-08-13)

### A.1 — Preflight
- `az login` as `hardik.jumnani123@gmail.com`; subscription = **Azure for Students**.
- Registered resource providers **Microsoft.Compute** and **Microsoft.Network**
  (were `NotRegistered` on the fresh sub; Storage already registered). Free.
- Quota (Central India): **Total Regional vCPUs = 6**; Basv2 family = 10; BS = 4.
  → the 2-vCPU `B2ats_v2` fits (uses 2/6). Gate: **PASS**.

### A.2 — Resource group — **free**
- `matila-prod-rg` (centralindia).

### A.3 — Networking — **free**
- VNet `matila-prod-vnet` — `10.0.0.0/16`.
- Subnet `matila-prod-subnet` — `10.0.1.0/24`.
- NSG `matila-prod-nsg` (attached to the subnet). Inbound rules:
  | Rule | Port | Source | Prio |
  |---|---|---|---|
  | allow-ssh | 22 | `14.194.79.194/32` (owner's IP) | 100 |
  | allow-http | 80 | Internet | 110 |
  | allow-https | 443 | Internet | 120 |
  | (default) | * | denied | — |
  - ⚠️ SSH is locked to `14.194.79.194` (dynamic/residential IP). If it rotates,
    update: `az network nsg rule update -g matila-prod-rg --nsg-name matila-prod-nsg -n allow-ssh --source-address-prefixes <NEW_IP>/32`

### A.4 — VM + disk + IP — **first billable** (2026-08-13)
- Public IP `matila-prod-ip` — Standard, **Static** → **`52.140.127.181`**. ~$3.65/mo.
- NIC `matila-prod-nic` — no NIC-level NSG (subnet NSG governs). Free.
- VM `matila-prod-vm` — `Standard_B2ats_v2` (2 vCPU / **891 MB** usable), Ubuntu
  22.04.5 LTS (gen2), private IP `10.0.1.4`. **Free** (750-hr student allowance).
- OS disk `matila-prod-osdisk` — Standard SSD, 30 GB (`nic-delete`/`os-disk-delete`
  = Delete, so the VM tearing down cleans them up). ~$3/mo.
- SSH: `ssh azureuser@52.140.127.181`, key `~/.ssh/id_rsa` on the owner's machine
  (`C:\Users\hardi\.ssh\`). **Gate: SSH verified working. PASS.**
- No swap yet (added in Phase B for the 1 GB constraint).

### A.7 — Prod Blob storage (2026-08-13)
- Storage account `matilaprodstore` (Standard_LRS, StorageV2, TLS1_2,
  **`allowBlobPublicAccess=false`**). Private `media` container.
- Connection string is a **secret** — not stored here. Retrieve on demand for
  the Phase B env file: `az storage account show-connection-string -g matila-prod-rg -n matilaprodstore -o tsv`
- Dev `matiladevstore` remains separate/untouched.

### A.8 — DNS (free Azure hostname, Option A)
- DNS label set on `matila-prod-ip` → **`matila-prod.centralindia.cloudapp.azure.com`**
  → resolves to `52.140.127.181`. Used for Let's Encrypt TLS in Phase C.
- (A branded Cloudflare domain can be swapped in later; not required.)

### Cost so far
| Resource | ~ Monthly (24/7) |
|---|---|
| VM `B2ats_v2` | $0 (free allowance) |
| Static public IP | ~$3.65 |
| OS disk (Std SSD 30 GB) | ~$3.00 |
| Blob `matilaprodstore` (media, few GB) | ~$0.50 |
| Azure DNS label | free |
| **Running total** | **~$7.15/mo** → within $100 for the year |

### Phase A — COMPLETE ✅
Gate met: all infra deployed; SSH works (from owner IP only); NSG limited to
22/80/443; FQDN resolves. Postgres + Redis run **on the VM** (localhost-private
by construction) and are installed in **Phase B**, which is the next step.

---

## Phase B — Deploy the application (2026-08-18)

Ran entirely over SSH (git-bash) as `azureuser`. Secrets flowed local → `scp` →
VM and were never printed. `/tmp` is cleared on reboot, so no transfer artifacts
persist.

### B.1 — OS prep
- 2 GB swap file (`/swapfile`, `fstab` persistent) for the 1 GB box.
- System packages: **Python 3.10.12**, **PostgreSQL 14.23**, **Redis 6.0.16**,
  **Nginx 1.18.0** (Ubuntu 22.04 stock).

### B.2 — PostgreSQL (self-hosted, localhost-only)
- Role `matila` + database `anonymous_chat`; listens on `127.0.0.1:5432` only.
- Tuned for 1 GB: `shared_buffers=128MB`, `max_connections=30`,
  `effective_cache_size=256MB`, `work_mem=4MB`.
- `DATABASE_URL` saved to `/etc/matila/.dburl` (secret).

### B.3 — Redis (self-hosted, localhost-only)
- `PING → PONG` on `127.0.0.1:6379`. Broker + channel layer + cache.

### B.4 — App code + venv
- Code at `/opt/matila` (owned by `azureuser`); `.venv` on
  `requirements/production.txt`: Django 5.1.5, daphne 4.1.2, channels 4.2.0,
  celery 5.4.0, redis 5.2.1, psycopg 3.2.3, azure-storage-blob 12.24.0,
  firebase-admin 6.6.0, gunicorn 23.0.0 (installed but unused — see B.7).
- **Fix:** razorpay imports `pkg_resources` at import time and the fresh venv had
  no `setuptools` → `ModuleNotFoundError`. Installed `setuptools<81` (80.10.2) and
  **pinned it in `requirements/base.txt`** so re-deploys don't regress.

### B.5 — Secrets
- `/etc/matila/env.production`, `firebase.json`, `.dburl` — all `0600`, owned by
  `azureuser` (the run-user, so systemd `EnvironmentFile=` and `manage.py` can read
  them). 17 keys; `DJANGO_SETTINGS_MODULE=config.settings.production`. Razorpay
  keys are `placeholder_phase_h` (real keys land in Phase H).

### B.6 — Migrate + static
- `manage.py check --deploy`: clean (the 66 issues are all `drf_spectacular.W001`
  schema-gen warnings — no `security.W*`, i.e. SSL/HSTS/cookie hardening satisfied).
- `migrate --noinput`: all migrations applied (incl. `notifications.0002_devicetoken`).
- `collectstatic --noinput`: 163 files → `/opt/matila/staticfiles`.

### B.7 — systemd units (consolidated 4 → 2 for the 1 GB box)
- **`matila-asgi.service`** — `daphne -b 127.0.0.1 -p 8000 config.asgi:application`.
  Serves **both** REST and WebSocket (drops the separate Gunicorn process).
- **`matila-celery.service`** — `celery -A config worker -B --concurrency=1`.
  Worker **with embedded beat** (`-B`, supported on Linux; on Windows dev it must
  be a separate process). `--concurrency=1` to conserve RAM.
- Both: `User=azureuser`, `EnvironmentFile=/etc/matila/env.production`,
  `Restart=always`, `enabled` for boot.

### B.8 — Nginx reverse proxy (HTTP; TLS is Phase C)
- Site `/etc/nginx/sites-available/matila` (enabled; stock `default` moved to
  `/etc/matila/nginx-default.disabled`). `/` and `/ws/` → `127.0.0.1:8000`
  (WebSocket `Upgrade`/`Connection` headers, 3600 s read/send timeout); `/static/`
  served directly from `/opt/matila/staticfiles`; `client_max_body_size 15M`.
- **`proxy_set_header X-Forwarded-Proto https;`** is pinned so Django's
  `SECURE_SSL_REDIRECT=True` doesn't 301-loop before TLS exists. **Change to
  `$scheme` (or leave `https`) once Phase C terminates real TLS.**

### B.9 — Gate: **PASS** ✅
- `matila-asgi` + `matila-celery` both `active` + `enabled`; Nginx/Postgres/Redis active.
- **Reboot test:** VM rebooted; all services auto-started; `/health/` 200 after boot.
- Celery `inspect ping` → `pong` (1 node); journal shows `beat: Starting…`.
- WS upgrade probe through Nginx → Daphne returned app-level `403` (origin
  validator), **not** `502` — proxy path reaches the ASGI stack.
- `/health/` returns `200 {"status":"ok"}` end-to-end via Nginx, incl. the public
  **`http://matila-prod.centralindia.cloudapp.azure.com/health/`** and raw IP.

### Phase B — COMPLETE ✅
Cost unchanged from Phase A (~$7.15/mo). Next: **Phase C** — Let's Encrypt TLS +
`wss://` + access-log token hygiene.

---

## Phase C — Nginx, TLS, wss://, log hygiene (2026-08-19)

> **Note:** the SSH source IP had rotated again (`115.99.130.118` → `14.194.79.194`);
> updated `allow-ssh` before starting (the standing dynamic-IP caveat).

### C.1 — Preflight
- FQDN still resolves → `52.140.127.181`; port 80 open, 443 free.
- **certbot 5.7.0** installed via snap (`snap install --classic certbot`).
- **HSTS hardening (code):** `production.py` had `INCLUDE_SUBDOMAINS`/`PRELOAD`
  hard-`True`. On the shared `*.cloudapp.azure.com` parent that is unsafe (we
  don't own siblings; `preload` is effectively irreversible), so both are now
  `config(..., default=False)` — **off** on this host, re-enable via env on a
  fully-owned domain. `SECURE_HSTS_SECONDS` stays 1 year.

### C.2 — Certificate (staging first)
- **Staging** issuance succeeded (validated the HTTP-01 flow without spending the
  real rate limit), then deleted.
- **Production** cert issued: `certbot certonly --nginx --cert-name matila -d
  matila-prod.centralindia.cloudapp.azure.com`. `certonly` so certbot does **not**
  rewrite our vhost. Cert at `/etc/letsencrypt/live/matila/`, expires **2026-11-17**,
  issuer Let's Encrypt (E-series). Registration email = `hardik.jumnani123@gmail.com`
  (the `ADMIN_EMAILS` ops contact).

### C.3 — TLS vhost
- Rewrote `/etc/nginx/sites-available/matila`:
  - **:80** → `return 301 https://$host$request_uri` (renewals use the certbot
    nginx authenticator, which injects the challenge location temporarily).
  - **:443** `ssl http2` — cert, **TLSv1.2 + TLSv1.3**, ECDHE-only cipher list
    (no DHE ⇒ no dhparam needed), session cache. `X-Forwarded-Proto $scheme`
    (was pinned `https` in Phase B). Same `/`, `/ws/` (Upgrade headers), `/static/`.
- Pushed the updated `production.py` to `/opt/matila` (tarball snapshot, not git),
  restarted `matila-asgi` to load the new HSTS config, reloaded Nginx.

### C.4 — Token-log hygiene
- **Nginx:** custom `log_format matila_notoken` logs `"$request_method $uri
  $server_protocol"` (uses `$uri`, **not** `$request`/`$request_uri`) → the
  `?token=<jwt>` on `wss://` handshakes never reaches disk.
- **Daphne:** its access log **did** include the query string (caught a real
  `"GET /ws/chat/…/?token=…"` line). Fixed by adding **`--access-log /dev/null`**
  to the `matila-asgi` ExecStart (Nginx is the token-safe log of record).
- **Verified:** fired a sentinel `?token=` over HTTPS + a wss upgrade, forced a
  buffer flush via restart → **0** hits in both the Nginx access log and the
  Daphne journal.

### C.5 — Auto-renewal
- Deploy hook `/etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh` (reloads
  Nginx after any successful renewal).
- `snap.certbot.renew.timer` **active** (fires twice daily).
- `certbot renew --dry-run` → **"all simulated renewals succeeded."**
  (An orphaned dry-run from an SSH timeout had to be killed first — it held the
  flock; `.certbot.lock` files are flock-based and free on process death.)

### C.6 — Gate: **PASS** ✅
- `https://FQDN/health/` → **200**; `http://FQDN/health/` → **301** to HTTPS.
- **HSTS** `max-age=31536000` present (no includeSubDomains/preload). `nosniff` present.
- TLS **1.1 refused; 1.2 + 1.3 accepted**; cert CN matches FQDN, LE issuer.
- `wss://…/ws/chat/{id}/` upgrade reaches the Channels stack over TLS (app-level
  `403` on a tokenless probe — the WS path, not the HTTP 404 resolver; full
  authenticated connect proven earlier in the emulator test).
- Token hygiene: **0** token hits in Nginx access log and Daphne journal.
- `renew --dry-run` succeeds; timer active; nginx-reload deploy hook wired.

### Phase C — COMPLETE ✅
App is now live on **HTTPS + `wss://`**. Cost unchanged (~$7.15/mo; the cert is
free). Next: **Phase D** — runtime config seeding + `ADMIN_EMAILS` allow-list.
**Frontend must switch to `https://` + `wss://` before pointing at prod.**

---

## Phase D — Runtime configuration seeding (2026-08-19)

### D.1 — Seed command
- New idempotent `apps/configuration/management/commands/seed_runtime_config.py`
  (`--dry-run` supported). Writes go through `ConfigurationService.set_config` /
  `.set_flag` (upsert → Redis cache-bust → audit row). Config already has
  code-level fallbacks; this **persists** launch-intent values to the DB so they
  are auditable and admin-editable.

### D.2 — Seeded on prod
- Ran on the VM → **11 `app_config` + 4 `feature_flag`** rows. Prices frozen
  (5900 / 8900 paise), questionnaire v1, gesture pool, versions 1.0.0,
  `support@matila.in`, minimal FAQ/guidelines placeholders.
- **Feature flags:** `image_messages_enabled=true`, `maintenance_mode=false`,
  **`payments_enabled=false`, `reveal_enabled=false`** — the last two stay OFF
  until Phase H go-live (prod has placeholder Razorpay keys; see `STASH.md`).

### D.3 — `/config` verified live
- `GET https://…/api/v1/config` returns the exact launch set (flags, pricing,
  questionnaire, versions, support email, faq, guidelines).
- **Encoding note:** confirmed the prod DB is `server_encoding=UTF8` and
  round-trips Unicode (em-dash + emoji) cleanly via the ORM. An apparent mojibake
  in `/config` was traced to a **local Windows `python -m json.tool`** decoding
  the UTF-8 response as cp1252 for display — not a server/DB issue. Kept the
  guidelines placeholder ASCII regardless.

### D.4 — Admin access verified live
- `ADMIN_EMAILS=hardik.jumnani123@gmail.com` (set in `env.production`). The admin
  gate (`IsAdminUser`) allows a Firebase-auth'd user whose `college_email` is on
  the list. **No bundled admin UI** — the admin surface is the JSON API under
  `/api/v1/admin/…`; Django's `/admin/` is a separate, unused system (see `STASH.md`).
- Minted an admin **ID token headlessly** on the VM: Firebase Admin SDK
  (`create_user` for the admin email + `create_custom_token`) → exchanged for an
  ID token via Identity Toolkit `signInWithCustomToken` (owner's Firebase **Web
  API Key**, a public client key — not stored here).
- Bootstrapped the session (`POST /auth/session` → **201**, created the prod
  admin user), then `GET /api/v1/admin/dashboard/stats` → **200**; unauthenticated
  → **401**. Authenticated-non-admin → **403** is covered by `test_admin_api`.

### D.5 — Flag toggle reflects live
- `PUT /api/v1/admin/feature-flags/maintenance_mode {"value":true}` → **200** →
  `/config` shows `true`; flipped back to `false` → `/config` shows `false`.
  Confirms the admin write path + cache invalidation end-to-end.

### D.6 — Gate: **PASS** ✅
`/config` matches launch intent · admin reaches `/admin/dashboard/stats` (200) /
unauth 401 / non-admin 403 (tested) · a flag toggle reflects live in `/config`.

### Phase D — COMPLETE ✅
Cost unchanged (~$7.15/mo). Next: **Phase E** — observability (Sentry, which also
activates the request-ID tag, + Azure Monitor + alerts).

---

## Phase E — Observability (2026-08-19) — all free-tier

Deliberately **budget-first**: paid Azure Log Analytics ingestion is skipped in
favour of Sentry (free), UptimeRobot (free), and a free in-app metrics sampler,
to protect the $100 runway. A paid dashboard can be added later if needed.

### E.1 — Sentry (errors only, free tier)
- `sentry-sdk==2.20.0` in `requirements/production.txt`; installed in the prod venv.
- Init in `production.py` (guarded on `SENTRY_DSN`): Django + Celery integrations,
  `send_default_pii=False`, `max_request_body_size="never"`, `traces_sample_rate=0`
  (errors only), and a `before_send` that strips `Authorization`/`Cookie` headers
  and redacts `?token=` from URLs (defence in depth vs the Phase-C token hygiene).
- `SENTRY_DSN` (+ `SENTRY_ENVIRONMENT=production`) added to `/etc/matila/env.production`.
  DSN is a client (send-only) key; EU-region project.
- **request-ID correlation auto-activates** — `apps.common.request_id._tag_sentry`
  tags every event once `sentry_sdk` is importable (no new code).

### E.2 — Deep readiness probe
- New `/health/ready` (`readiness_check`): checks Postgres + Redis/cache, returns
  200 or 503 with a per-check breakdown. `/health/` stays shallow for the LB/uptime
  ping. Verified live → `200 {"database":"ok","cache":"ok"}`.

### E.3 — Free metrics sampler
- `apps/common/tasks/monitoring.py` → `sample_system_metrics` (Celery beat, every
  5 min): logs **Redis used_memory**, **Celery backlog** (default-queue depth), and
  **DB connections** (`pg_stat_activity`); raises a Sentry `warning` on a threshold
  breach (300 MB / 100 / 24-of-30). Values visible via `journalctl` — no paid
  ingestion. Verified on prod (`redis ~1.3 MB, backlog 0, db 2`); beat registered
  the task.

### E.4 — Uptime monitoring (UptimeRobot, free) — **done**
- UptimeRobot HTTP(s) monitor on
  `https://matila-prod.centralindia.cloudapp.azure.com/health/` (5-min interval),
  alerting `support@matila.in` + `hardik.jumnani123@gmail.com`.
- **Fix:** UptimeRobot sends **HEAD** by default; `/health/` was `@require_GET`
  (405) → monitor read "down". Switched both health views to `require_safe`
  (GET+HEAD) — `e8105f8`. HEAD now 200.
- **Alert test passed:** stopped `matila-asgi` 05:49–05:56 UTC (~7 min, spanning a
  5-min check) → **DOWN** email to both inboxes; auto-restart → **UP** email.
  Confirmed received.

### E.5 — Verification
- Deliberate Sentry error sent (`event_id=05314c1e…`) tagged
  `request_id=ed33d3b71deb4495a7b06e1d0c212e65`, PII-scrubbed → confirm in the
  Sentry dashboard. `/health/ready` 200. Sampler + beat live.

### Phase E — COMPLETE ✅
Gate met: deliberate error in Sentry with `request_id` (PII-scrubbed); stopping
`matila-asgi` fired the UptimeRobot alert to both inboxes; core metrics
(Redis/Celery/DB) sampled with thresholds. Cost unchanged (~$7.15/mo —
Sentry/UptimeRobot/sampler are all free). Next: **Phase F** — backups & DR.

---

## Phase F — Backups & disaster recovery (2026-08-19)

**Deviation:** the plan assumed Azure PostgreSQL Flexible Server (managed backups +
PITR). We self-host Postgres on the VM, so Phase F is scheduled **logical backups
to Blob** + **VM snapshots**, with a proven restore. Runbook: `docs/RESTORE.md`.

### F.1 — Backup storage + retention
- Private `backups` container in `matilaprodstore` (created by the backup command).
- **Blob lifecycle rule** `delete-old-backups`: delete `backups/` blobs older than
  **14 days** (hands-off retention, no prune code).

### F.2/F.3 — Nightly DB backup
- `apps/common/management/commands/backup_database.py`: `pg_dump -Fc`
  (`PGPASSWORD` via env, never argv) → upload to `backups/` via the Azure SDK;
  Sentry-alerts on failure.
- **systemd** `matila-backup.service` (oneshot, `EnvironmentFile`) +
  `matila-backup.timer` (`02:30 UTC` daily, `Persistent=true`).
- ⚠️ Run backups **via the systemd service**, not `set -a; source env.production`
  — bash `source` splits the storage connection string on its `;`, truncating it
  (systemd `EnvironmentFile` parses it correctly). Verified: an 86 KB dump uploaded.

### F.4 — Restore drill (**gate**)
- Downloaded the latest Blob dump → restored into scratch DB `anonymous_chat_restore`
  → row counts **matched live** (`app_config=11, feature_flags=4, users=1,
  migrations=31`) and `migrate --check` reported **no pending migrations** → dropped
  the scratch DB. **Restore proven end-to-end.**

### F.6 — Weekly VM snapshots
- VM given a **system-assigned managed identity** (`6830c405-…`); least-privilege
  custom role **"Matila Snapshot Manager"** (snapshots read/write/delete; disks
  read + begin/endGetAccess — the last two are required for snapshot-by-copy)
  scoped to the RG.
- `ops/vm-snapshot.sh` (IMDS token + ARM REST, no `az` on the box) creates an
  **incremental** OS-disk snapshot and prunes to the newest 4; `matila-vm-snapshot.timer`
  runs it **weekly (Sun 03:00 UTC)**. Verified: `matila-osdisk-…` snapshot
  `provisioningState=Succeeded`, incremental.

### Phase F — COMPLETE ✅
Gate met: a restore **succeeded** end-to-end (not just backup existence). Added
cost is negligible (tiny Blob dumps + incremental snapshots ≈ well under $1/mo) —
running total still ~$7–8/mo. Next: **Phase G** — prod E2E + ~100-user load test.
