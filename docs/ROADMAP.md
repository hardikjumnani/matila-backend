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

- `XX` **Phase A — Provision Azure** — resource group, VM (Ubuntu), PostgreSQL
  Flexible Server, Azure Cache for Redis, prod Blob account, DNS, NSG.
- `XX` **Phase B — Deploy the app** — the four processes under systemd (Gunicorn,
  Daphne, Celery worker, Celery beat); migrate; collectstatic.
- `XX` **Phase C — Nginx + TLS + `wss://`** — cert + auto-renew; token-log hygiene.
- `XX` **Phase D — Runtime config seeding** — prices/flags/questionnaire/versions;
  `ADMIN_EMAILS` allow-list.
- `XX` **Phase E — Observability** — Sentry (activates the request-id tag) +
  request-ID correlation + Azure Monitor + alerts.
- `XX` **Phase F — Backups & disaster recovery** — prove a point-in-time restore.
- `XX` **Phase G — Prod end-to-end validation + ~100-user load test.**
- `XX` **Phase H — Razorpay live + webhook + go-live + rollback rehearsal.**

---

**Where the pointer sits:** everything through the request-ID milestone is done
and committed. The next step is **Azure Phase A** (hands-on infra, guided one
gated phase at a time — see `docs/DEPLOYMENT_PLAN.md`).
