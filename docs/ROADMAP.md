# Matila Backend — Roadmap

**What we're building:** the production backend for Matila — an anonymous,
delayed-chat app for verified college students (matched anonymously → 72h
anonymous chat → optional mutual paid identity reveal → ratings/reports). Django
+ DRF + Channels + PostgreSQL + Redis + Celery, with Firebase Auth/FCM, Razorpay,
and Azure Blob Storage. The Flutter client lives in a separate repo.

**End goal:** a production deployment on **Azure** serving the live app to real
users — backend behind HTTPS/`wss://`, Flutter client talking to it.

**Legend:** `OO` = done · `XX` = not done

---

## Build & validate

- `OO` **Backend build (Steps 1–10)** — all domains (users, verification,
  matchmaking, chats, messaging, reveal, payments, reports, ratings,
  notifications, configuration, audit, admin_panel, common); tests + CI.
- `OO` **Local environment stood up + validated live** — PostgreSQL 16, Redis
  (Memurai), Firebase Auth, Azure Blob Storage.
- `OO` **API contract reconciliation with the frontend** — `Frontend/API_CONTRACT.md`
  is backend-authoritative.
- `OO` **Full-feature live emulator test** (2026-08-04) — every frozen feature
  verified end-to-end against the real backend on the emulator: sign-in →
  onboarding → verification → matchmaking → anonymous chat (text/image/view-once
  + all WS events) → reveal + unmask → rating → report → expire/extend/
  reveal-on-expiry → real FCM push.
- `OO` **Pre-deploy code milestone: request-ID correlation** (`a32c320`) —
  `X-Request-ID` traced across REST → Celery → WebSocket → audit; Sentry half is a
  guarded no-op until Phase E.

## Deploy to Azure (details in `docs/DEPLOYMENT_PLAN.md`)

- `OO` **Phase A — Provision Azure** (2026-08-13) — `matila-prod-rg`; one
  free-tier `B2ats_v2` VM (Ubuntu 22.04) that runs everything; static public IP +
  Azure DNS label (`matila-prod.centralindia.cloudapp.azure.com`); prod Blob
  account; NSG (SSH owner-IP only, 80/443 open). **Postgres + Redis self-hosted on
  the VM** (cost-optimized for max $100-credit runway — replaces Flexible Server +
  Azure Cache). See `AZURE_PROVISION_LOG.md`.
- `OO` **Phase B — Deploy the app** (2026-08-18) — code at `/opt/matila`, venv on
  `requirements/production.txt`; `/etc/matila/env.production` (`0600`); `migrate` +
  `collectstatic`; systemd units **`matila-asgi`** (Daphne serving REST **and** WS)
  and **`matila-celery`** (worker + embedded beat via `-B`) — consolidated from
  four processes to two to fit the 1 GB box; Nginx reverse proxy (HTTP). Gate met:
  both services active + auto-restart, **survived a reboot**, `/health/` 200
  end-to-end through Nginx (incl. public FQDN), worker+beat live.
- `OO` **Phase C — Nginx + TLS + `wss://`** (2026-08-19) — Let's Encrypt cert for
  the FQDN (auto-issued via certbot nginx authenticator, staging-validated first);
  HTTPS with TLS1.2/1.3 + ECDHE ciphers (SSL-Labs-A config), HTTP→301→HTTPS, HSTS
  (`max-age=1y`, **no** includeSubDomains/preload on the shared Azure host);
  `wss://` upgrade proven to the Channels router. **Token-log hygiene:** Nginx logs
  `$uri` (query stripped) and Daphne's access log is sent to `/dev/null` — verified
  zero token hits in both. Auto-renew: certbot timer active + nginx-reload deploy
  hook; `renew --dry-run` succeeds.
- `XX` **Phase D — Runtime config seeding** — prices/flags/questionnaire/versions;
  `ADMIN_EMAILS` allow-list.
- `XX` **Phase E — Observability** — Sentry (activates the request-id tag) +
  request-ID correlation + Azure Monitor + alerts.
- `XX` **Phase F — Backups & disaster recovery** — prove a point-in-time restore.
- `XX` **Phase G — Prod end-to-end validation + ~100-user load test.**
- `XX` **Phase H — Razorpay live + webhook + go-live + rollback rehearsal.**

---

**Where the pointer sits:** Azure Phases A–C are done — the app is live over
**HTTPS + `wss://`** at `https://matila-prod.centralindia.cloudapp.azure.com/`
(valid Let's Encrypt cert, auto-renewing), running under systemd (Daphne +
Celery) behind Nginx. The next step is **Phase D — runtime configuration
seeding** (prices/flags/questionnaire/versions + the `ADMIN_EMAILS` allow-list).
See `docs/DEPLOYMENT_PLAN.md`.

> **Frontend coordination (pending):** the Flutter client must switch its base
> URL to `https://…` and sockets to `wss://…` when pointing at prod (it currently
> targets the dev `http://10.0.2.2:8000` / `ws://` loopback). Not a backend task.
