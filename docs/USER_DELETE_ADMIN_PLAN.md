# Admin "Delete user" (complete erasure) — Plan (Backend + AdminPanel)

## Goal
In the AdminPanel Users tab, a **Delete user** button alongside Suspend / Ban /
Activate that triggers a backend **complete, cascading erasure** of the user and
all their data, following right-to-erasure (GDPR / India DPDP) practice.

## What already exists (reuse, do NOT rebuild)
`apps/users/services/erasure_service.py` -> `UserErasureService.erase(user,
requested_by=...)` already does the industry-standard erasure:
- **Deletes blob objects:** profile photo, verification ID + gesture-selfie docs,
  all sent chat media (best-effort; storage errors logged, never block).
- **Hard-deletes personal rows:** messages, verification_requests, device_tokens,
  notifications, reveal ParticipantDecisions, match_queue entries,
  chat_participations, ratings the user authored.
- **Deletes the Firebase Auth identity** (login can never be reused).
- **Anonymizes the user row** (firebase_uid, college_email, full_name, photo,
  gender, intent, prefs scrubbed; `account_status = DELETED`) because
  **payments (financial)** and **reports (safety)** PROTECT-reference it and must
  be retained PII-free (mandatory financial retention / platform-safety basis).
- **Audits** it (`action="user.erased"`, actor = admin, counts in metadata; no PII).

Only a CLI exposes it today (`manage.py erase_user --email ... --yes --by ...`).

## Backend change (small): expose it as an admin endpoint
- **New view** `AdminUserEraseView(AdminAPIView)` (IsAdminUser), route
  **`POST /api/v1/admin/users/{id}/erase`** (consistent with suspend/ban/activate,
  which are `POST /{id}/<action>`).
- **Body (irreversibility guard):** `{"confirm": "<the user's college_email>"}`.
  The endpoint must verify `confirm` equals the target's current email (mirrors the
  CLI's email-match guard) and refuse otherwise -> `VALIDATION_ERROR`. This stops a
  mis-clicked or mis-targeted erase.
- **Safeguards:**
  - Idempotency: refuse if `account_status == DELETED` already (or email starts with
    `erased-`) -> `CONFLICT "already erased"`.
  - Refuse to erase an **admin account** (email on `ADMIN_EMAILS`) and **self**.
  - Calls `UserErasureService().erase(user, requested_by=str(request.user.id))`.
  - Returns the erasure summary (`blobs_deleted, firebase_deleted, messages,
    verification_requests, device_tokens, notifications, reveal_decisions,
    match_queue_entries, chat_participations, ratings_given`).
- **Audit** is already emitted by the service.

## Recommended enhancement: end the user's active chats gracefully
Today erasure deletes `chat_participations`, leaving the OTHER participant with a
one-sided/stale chat (seen when Hardik 2 was erased). Add to the erase path: for
each ongoing chat the user is in, call `ChatService.end_chat(reason=USER_EXIT/ADMIN)`
so the partner's chat is cleanly ENDED (read-only) and they get the normal
`chat.state_updated` + notification, instead of a broken chat. (Do this before/within
the erase, inside the same flow.)

## Optional (industry variant, not required now): scheduled/soft erase
Some platforms do a **grace window** — mark the account for deletion and hard-erase
after N days (lets a mistaken delete be reversed). The current behavior is immediate.
For an admin-initiated test-account cleanup, immediate is fine; a 30-day scheduled
erase can be a later enhancement (a `deletion_scheduled_at` + a Celery sweep).

## AdminPanel change (the button)
- In the Users tab (user detail, next to Suspend / Ban / Activate), add a **Delete
  user** button, visually **danger/destructive** (red, separated from the others).
- **Confirmation modal** (because it is irreversible): require the admin to **type
  the user's email** to enable the confirm button; show exactly what will be deleted
  vs retained (payments/reports kept PII-free). On confirm, `POST
  /admin/users/{id}/erase` with `{"confirm": "<email>"}`.
- Respect the panel's **PROD write-guard** (erase is a write -> only when PROD writes
  are unlocked; see B0006 plan).
- On success, show the returned summary and mark the user DELETED (anonymized) in the
  list; the row stays (anonymized), it does not vanish.

## Tests
- Backend: erase via the endpoint deletes the personal rows + anonymizes + audits;
  wrong `confirm` -> 400; already-deleted -> 409; admin/self -> refused; non-admin ->
  403. (Reuse the existing erasure-service tests; add API-level ones.)
- Confirm active chats end for the partner.

## Industry-practice checklist (what makes this "complete + safe")
- Right-to-erasure: personal data + media + auth identity purged; PII-free legal
  records (payments/reports) retained. [done in service]
- Irreversible-action safeguards: typed-email confirmation, admin-only, audited,
  idempotent, self/admin protected. [endpoint adds these]
- Login cannot be reused (Firebase identity deleted). [done]
- Graceful partner experience (end their chat). [enhancement]
- Storage failures never block the DB erasure; logged. [done]

## Coordination
- Backend ships the endpoint + guards + chat-end enhancement + tests.
- AdminPanel (EXTERNAL_BRIDGE): add the danger Delete button + typed-email confirm
  modal behind the PROD write-guard, calling `POST /admin/users/{id}/erase`
  `{confirm}`. (Post on owner's go.)
