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

### 3. Production WebSocket `Origin` policy (before the prod cutover)
- **What:** prod runs `DEBUG=False`, so Channels' `AllowedHostsOriginValidator` is
  active and the native mobile socket (which sends no/again a non-matching
  `Origin`) will **403** on `wss://…/ws/…`. This is the flip-side of the dev-only
  origin skip (`4c46f9a`).
- **Why deferred:** only bites once the Flutter client points at prod. Also tracked
  in `AI_BRIDGE.md` (open coordination items, BE `[50045]`).
- **Do later** (before the Phase G prod dress rehearsal): pick **(a)** FE sends
  `Origin: https://matila-prod.centralindia.cloudapp.azure.com` on the handshake,
  or **(b)** BE adds a prod-safe origin policy for the token-authenticated mobile
  socket (BE-recommended — native apps have no browser cross-site-WS threat and the
  socket is already Firebase-authenticated). Implement whichever we agree on.

---

## Done

_(nothing yet)_
