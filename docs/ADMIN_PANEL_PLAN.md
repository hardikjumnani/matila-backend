# Admin panel + verification review

## The verification flow
1. User: `GET /verification/gesture` → a random gesture (liveness/anti-spoof).
2. User uploads `POST /verification/upload-college-id` + `POST /verification/upload-gesture-selfie`
   (selfie performing the gesture), then `POST /verification/submit` → status **PENDING**.
3. Admin reviews and decides → the user's `verification_status` flips; they're
   notified (push) and it's audit-logged.

## Admin API (already built, `/api/v1/admin/...`, `IsAdminUser`)
- `GET /admin/verifications?status=PENDING` — review queue (filter: PENDING /
  APPROVED / REJECTED / RESUBMISSION_REQUIRED / ALL).
- `GET /admin/verifications/{id}` — the application **with signed (viewable) URLs**
  for the college-ID photo + gesture selfie.
- `POST /admin/verifications/{id}/approve | reject | request-resubmission` — each
  takes `{"notes": "..."}`, is atomic, updates the user, notifies, audits.
- Also: reports moderation, user suspend/activate/ban, feature flags, app-config,
  audit logs, dashboard stats.
- **Auth:** an admin is a Firebase user whose `college_email` is in `ADMIN_EMAILS`
  (env allow-list) — no separate admin accounts.

## Local dev panel (built — `apps/admin_panel/ui_views.py`)
A self-contained console at **`/admin-panel/`** (served by Django, **DEBUG-only**)
for local review. It authenticates via the **dev-auth bypass**: a bearer token
`dev:<email>` is accepted only when `AUTH_DEV_BYPASS=True` (dev settings; **False
in base + production**, with a prod fail-fast guard). This is a dev convenience /
reference implementation — **not** the production admin surface.

To use locally: run the dev backend, open `http://localhost:8000/admin-panel/`,
sign in with an admin email from `.env ADMIN_EMAILS`. Seed demo applications with
`manage.py seed_demo_verifications --count 4`.

## Production panel — separate FE workstream (#1)
A **standalone admin web app** (not the Flutter consumer app, not Django admin),
consuming the admin API:
- **Auth:** admin signs in with their Firebase account (email-link) → ID token →
  `Authorization: Bearer <token>`; backend gates on `ADMIN_EMAILS`. (No dev-bypass
  in prod.)
- **Screens:** verification queue → detail (ID + selfie side by side) →
  approve/reject/request-resubmission with notes; plus reports and user management
  reuse the same admin API.
- **Hosting:** static SPA (e.g. nginx on the VM or a separate host); desktop-first
  (reviewing documents).
- The dev panel above is the reference for screens + API calls.
