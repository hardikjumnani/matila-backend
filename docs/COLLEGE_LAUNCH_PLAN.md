# Per-college launch — plan & implementation

> Status: **built.** Implemented 2026-10-02. Each college has a launch date;
> users onboard + verify before launch and wait on a countdown, and the core app
> (matchmaking + profile edits) opens only at the college's launch date.

## 1. Model: `College` + membership

- **`colleges.College`** (`apps/colleges/models.py`): `code` (unique), `name`,
  `allowed_email_domains` (JSON list, lowercase), `launch_date` (nullable),
  `is_active`. `is_launched` = `launch_date is not None and now >= launch_date`.
- **`users.User.college`** — FK, **NOT NULL**, `on_delete=PROTECT`. One user → one
  college; one college → many users. The column stays NOT NULL via a **callable
  default** (`_default_college_id`) that parks any create omitting a college on the
  catch-all **`UNASSIGNED`** college (so tests/legacy rows never break). Real
  sign-ups set the resolved college explicitly in the auth bootstrap.
- **Unassigned** is seeded with `launch_date = 2000-01-01` → always "launched",
  so the catch-all never gates legacy/seed/test accounts. No real sign-up lands
  there (unknown domains are rejected, below).

## 2. Membership is derived from the verified email domain

- `CollegeService.resolve_for_email(email)` → the active college whose
  `allowed_email_domains` contains the email's domain, else `None`.
- **Sign-up (`AuthService.bootstrap_session`)**: first-time users get their college
  resolved from the Firebase email. **Unknown domain → `COLLEGE_NOT_SUPPORTED`
  (403)** — "Your college isn't on Matila yet." No account is created. No college
  picker; membership is purely domain-driven.

## 3. The launch gate (derived, no explicit flag)

"Ready to enter" = `verification_status == APPROVED` **and** `now >= launch_date`.
There is no status/flag — it's computed from the college each time.

- **Matchmaking** (`MatchmakingService._check_eligibility`): after the verified
  check, `is_user_launched` must be true, else **`COLLEGE_NOT_LAUNCHED` (403)** —
  "Matchmaking opens when your college launches."
- **Profile edits** (`AuthService.update_profile`): once a user has onboarded
  (`onboarding_completed_at` set), edits are locked pre-launch →
  **`COLLEGE_NOT_LAUNCHED`**. Initial onboarding (while `onboarding_completed_at`
  is `None`) and the whole verification flow stay **open** before launch.
- **Next action** (`_determine_next_action`): an APPROVED-but-pre-launch user
  gets `WAIT_FOR_VERIFICATION` (not `GO_HOME`), so the client stays on the waiting
  screen, which doubles as the countdown.

## 4. What the client sees (countdown payloads)

Both the session user payload (`UserSerializer`) and `GET /verification/status`
expose:
- **`college`**: `{ code, name, launch_date (ISO|null), launched (bool) }` or
  `null`.
- **`launched`**: bool — whether the user may enter the app.

The FE renders a **countdown to `college.launch_date`** on the waiting screen when
`launched` is false, and routes into the app when true.

## 5. Notification cycle

- **On approval (inline, per user)**: the verification approval notification is
  launch-aware — pre-launch it reads "You're verified! Matila launches at
  {college} soon — watch the countdown."; post-launch "…You can start matching
  now." (`VerificationService._review`).
- **Scheduled countdown (per college, idempotent)**: Celery beat task
  `apps.colleges.tasks.send_launch_notifications` (every 10 min) sweeps active
  colleges with a `launch_date` and fires milestones **T-7d, T-1d, T-1h, LAUNCH**
  to each college's **APPROVED + ACTIVE** members.
  - Exactly once per `(college, milestone)` via the `launch_notifications` table
    (unique constraint).
  - A milestone is **sent** only if it became due within the last hour
    (`_FRESH_WINDOW`); milestones already long past (launch set/edited late) are
    **recorded but suppressed**, so nobody gets a stale "7 days to go" blast.

## 6. Admin

- **API** (admin-only, `ADMIN_EMAILS`): `GET /admin/colleges` (list with launch
  state + member counts), `GET /admin/colleges/{id}`, `PATCH /admin/colleges/{id}`
  to set `launch_date` / `name` / `allowed_email_domains` / `is_active`. Changes
  are audited (`college.updated`).
- **Dev panel**: the local admin console (`/admin-panel/`, DEBUG-only) has a
  **Colleges** tab to view/set each college's launch date.

## 7. Seeding

`python manage.py seed_colleges` creates the pilot colleges (BITS Pilani, Scaler)
with a default launch 7 days out. Flags:
- `--demo` adds a DEMO college mapping common test domains (`college.edu`,
  `dev.local`, `gmail.com`, …) — **never run with `--demo` in production**.
- `--launch-in-days N` / `--demo-launch-in-minutes M` set offsets.
- `--reset-launch` overwrites an existing launch date (otherwise preserved).
- `--reassign` re-resolves existing users onto their domain's college.

## 8. Relationship to multi-college matching

The `College` model is the foundation for the parked multi-college matching plan
(`docs/MULTI_COLLEGE_PLAN.md`). This feature only adds **launch gating + domain
membership**; cross-/intra-college match scoping is still parked.
