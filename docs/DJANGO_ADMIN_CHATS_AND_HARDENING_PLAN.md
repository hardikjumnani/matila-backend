# Django admin: Chats participant display + security hardening - Plan

Two tasks: (1) show both chat participants by full name in the Chats admin; (2) audit
the Django `/admin/` for data leakage and harden it.

---

## PART 1 - Chats tab shows User 1 + User 2 (full name)

Today `ChatAdmin` (`apps/chats/admin.py`) lists chat id/status/counts and shows
participants only via a raw-id inline (ids, not names). Add the two participants by name.

Change `apps/chats/admin.py` `ChatAdmin`:
- Add `get_queryset` with `.prefetch_related("participants__user")` (avoid N+1 in the list).
- Add two display methods `user_1` and `user_2` (participants ordered by `joined_at`)
  returning each participant's `user.full_name`, falling back to `college_email` then
  `"(unnamed)"` (full_name is blank for erased/anonymized users). Add both to
  `list_display` (after `id`). Optionally a combined `participants` ("A <-> B").
- In `ChatParticipantInline`, add a readonly `user_full_name` so the detail view shows the
  name next to the raw-id user field.
- Also make the participant searchable by name: add `participants__user__full_name` to
  `ChatAdmin.search_fields`.

Display-only, no model/migration change. Note: this puts real names in the admin list, so
it is only as safe as admin access itself - which Part 2 tightens.

---

## PART 2 - Security / no-leakage audit + hardening

### Verified live on prod (2026-10-23)
Good (already in place):
- `DEBUG=False`; `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`,
  HSTS, `SECURE_CONTENT_TYPE_NOSNIFF` all on; dev bypasses hard-blocked; `ALLOWED_HOSTS`
  explicit; production is JSON-only (no browsable DRF).
- Anonymous access leaks nothing: `/admin/`, `/admin/users/user/`,
  `/admin/privacy/leakevent/` all return **302 -> login** when unauthenticated.
- Exactly **one** superuser on prod: `hardik@matila.in`. The weak local
  `admin/matila-admin` is NOT on prod. No other staff accounts.

Residual risks:
1. **`/admin/` is reachable from any IP** (nginx has no restriction) and Django admin has
   **no login rate-limit/lockout** -> brute-force surface for the single credential.
2. **Full-PII blast radius once authenticated**: nearly every model is registered
   (users incl. `firebase_uid`, messages, payments, `DeviceToken.token`, verification doc
   URLs, and privacy `LeakEvent.raw_message`/`matched_span` = the exact leaked PII), all
   add/change/deletable by a superuser. A compromised admin = full read + destructive write.
3. The superuser password was typed into chat earlier -> should be rotated.
4. Default `/admin/` path (bot noise). Minor.

### Hardening plan (ranked)
1. **Restrict `/admin/` at the edge (highest leverage).** Pick one:
   - (a) nginx HTTP Basic auth on `location /admin/` + `/static/admin/` (a second
     credential before Django's login) - robust against bots/brute-force and does not
     depend on a static IP (owner's IP rotates like SSH). **Recommended.**
   - (b) nginx IP allow-list to the owner's IP(s) (mirrors the SSH NSG) - strongest, but
     needs updating when the residential IP rotates.
   - (c) Disable Django `/admin/` on prod entirely (gate `path("admin/", admin.site.urls)`
     behind a setting, like the `admin-panel/` UI is DEBUG-gated) and rely on the custom
     admin API + AdminPanel. Strongest, but the owner is actively using Django admin.
   Recommend (a) now; (b)/(c) optional.
2. **Rotate the superuser password** (it was shared in chat); keep one strong unique
   superuser, non-obvious username.
3. **Shrink the blast radius in code** (`apps/*/admin.py`): make high-risk models
   **read-only in admin** (`has_add/change/delete_permission -> False`) - users, messages,
   chats, payments, privacy events, verification, device tokens, ratings, reports, reveal
   (keep editable only what ops needs: `FeatureFlag`, `AppConfig`, `College`). Prevents a
   compromised/fat-fingered admin from deleting or mutating core data.
4. **Mask the most sensitive fields** in those admins: exclude or readonly `firebase_uid`
   (users), `DeviceToken.token`, verification doc URLs, payment provider ids; keep privacy
   `raw_message` visible (T&S needs it) but be aware it is leaked PII - acceptable under
   restricted + read-only admin.
5. **Login hardening (optional, defense in depth):** `django-axes` (lockout after N failed
   logins) or an nginx rate-limit on `/admin/login/`; shorten admin session
   (`SESSION_COOKIE_AGE`); consider 2FA (`django-two-factor-auth`).
6. Keep the Django admin action log (`LogEntry`) for forensics (already on). Optionally
   move `/admin/` to an obscure path.

### Leakage conclusion
No anonymous/unauthenticated leak exists today (all admin pages gate to login, DEBUG off,
one superuser, API JSON-only). The real exposure is **credential-compromise or brute-force
-> full PII + destructive writes**. The fix is: restrict access to `/admin/` (step 1),
rotate the credential (step 2), and shrink the authenticated blast radius (steps 3-4).

### Suggested order
1 (nginx basic-auth) + 2 (rotate) now = quick + biggest risk reduction; then 3-4 (code,
read-only + field masking) in a deploy; 5-6 optional.

## Open decisions for the owner
1. Restrict `/admin/` via: nginx Basic auth (rec) / IP allow-list / disable-on-prod?
2. Make the listed admin models read-only (rec) - any you want left editable beyond
   FeatureFlag/AppConfig/College?
3. Add brute-force lockout (django-axes) now or later?
