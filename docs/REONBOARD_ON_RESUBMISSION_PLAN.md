# Re-onboarding on Resubmission — Plan

## Goal
When an admin requests **resubmission**, route the user back through **COMPLETE
ONBOARDING** again, instead of sending them straight to `SUBMIT_VERIFICATION`.

## Embedded question: does `next_action=COMPLETE_ONBOARDING` share pre-data?
**Yes.** The session payload (`SessionResponseSerializer`) always includes the
full `UserSerializer` next to `next_action`: `college_email, full_name, gender,
intent, gender_preferences, date_of_birth, college` (+ launch info). So when we
send the user back to onboarding, the client already has their existing values
and can **pre-fill** the re-onboarding screens; nothing is blank.

## Current behavior (why it goes to verification today)
`AuthService._determine_next_action` (apps/users/services/auth_service.py):
1. `onboarding_completed_at is None` → `COMPLETE_ONBOARDING`
2. `APPROVED` → `GO_HOME` (or `WAIT_FOR_VERIFICATION` pre-launch)
3. `REJECTED` / `RESUBMISSION_REQUIRED` → `SUBMIT_VERIFICATION`
4. `PENDING` → `WAIT_FOR_VERIFICATION` if a request was submitted, else `SUBMIT_VERIFICATION`

The `COMPLETE_ONBOARDING` gate is purely `onboarding_completed_at is None`. A
resubmission-required user already has `onboarding_completed_at` set, so they get
`SUBMIT_VERIFICATION`.

## Recommended approach (Approach 1 — minimal, reuses the existing gate)
When the admin requests resubmission, also **reset `onboarding_completed_at =
None`** on the user, in the same transaction as the status change.

Resulting flow:
- Admin requests resubmission → `verification_status = RESUBMISSION_REQUIRED`
  **and** `onboarding_completed_at = None`.
- Next session bootstrap → `COMPLETE_ONBOARDING` (the onboarding gate is checked
  first), with the user's profile pre-data in the payload.
- User re-does onboarding (`PATCH /users/me` + `complete-onboarding`) → sets
  `onboarding_completed_at` again.
- Next session → `SUBMIT_VERIFICATION` (still `RESUBMISSION_REQUIRED`) → re-submit.
- Net: **resubmission → re-onboard → re-verify.**

No change to `_determine_next_action` is needed (it already gates on
`onboarding_completed_at`). **Do not wipe the profile fields** — keep them so the
client pre-fills; re-onboarding overwrites whatever the user re-submits.

### Backend changes (small, no migration)
1. `VerificationService.request_resubmission` → `_review` (resubmission branch
   only): set `user.onboarding_completed_at = None` and add it to the `user.save`
   `update_fields`. Leave approve/reject untouched (reject stays terminal).
2. Tests: assert `request_resubmission` nulls `onboarding_completed_at`; assert a
   session bootstrap for that user returns `COMPLETE_ONBOARDING`; then after
   re-onboarding returns `SUBMIT_VERIFICATION`. Update existing resubmission tests.

### Interactions / edge cases
- **DOB is set-once.** `complete-onboarding` requires DOB to be present; it is
  already set, so the requirement passes, but the set-once rule means it cannot be
  changed. The client must render DOB **pre-filled / read-only** on re-onboarding.
  (No backend change; FE handling. Decide separately whether resubmission should
  *relax* set-once — default: keep set-once.)
- **`IsOnboardingCompleted` permission.** Verification endpoints require onboarding
  complete; while `onboarding_completed_at is None` they return 403
  `ONBOARDING_INCOMPLETE` until the user re-onboards. This is consistent with the
  re-onboard-first flow (they cannot skip ahead to verification).
- **Verification attempts are append-only.** Re-submitting creates a new attempt;
  old attempts are retained. The reset does not touch any draft attempt.
- **Resubmission note.** The admin's `review_notes` is currently surfaced as a
  banner on the submit screen. The client may also want to show it during
  re-onboarding so the user knows why they are back. (FE decision.)
- **Matchmaking / other `onboarding_completed_at` gates.** A resubmission-required
  user is not verified, so they are not matchmaking-eligible anyway; no impact.

## Approach 2 (flexible alternative — more work)
Give the admin a choice per resubmission: `request_resubmission(reonboard: bool)`.
`reonboard=True` resets `onboarding_completed_at` (Approach 1); `False` keeps
today's verification-only flow. Adds an admin API param + an AdminPanel toggle +
FE must support both entry points. Use only if both behaviors are wanted.

## FE / AdminPanel coordination (bridge, owner-directed)
- **FE (AI_BRIDGE):** on `next_action=COMPLETE_ONBOARDING` for a user who has
  already verified before, pre-fill onboarding from the session profile; render DOB
  read-only (set-once); optionally show the resubmission note. Confirm the
  onboarding flow handles re-entry (it previously only ran for brand-new users).
- **AdminPanel (EXTERNAL_BRIDGE):** "Request resubmission" now also sends the user
  back through onboarding. If a verification-only resubmission is ever wanted,
  that is Approach 2 (a toggle).

## Rollout
Backend change + tests, then deploy. Runtime-safe (no migration). The FE
re-onboarding-entry handling should ship in tandem; otherwise a resubmission user
lands on an onboarding screen that may not pre-fill or may re-ask set-once DOB.

## Open decisions
1. Approach 1 (always re-onboard on resubmission) vs Approach 2 (admin toggle)?
2. Should re-onboarding relax DOB set-once? Default: keep set-once.
