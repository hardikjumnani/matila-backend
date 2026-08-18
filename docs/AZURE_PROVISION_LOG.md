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
