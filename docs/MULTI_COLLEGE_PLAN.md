# Multi-college support — plan (parked for later)

> Status: **NOT implemented.** Matching is currently a single global pool. This is
> the agreed plan for when we onboard more colleges and want collegemates to match
> only within their own college. Parked 2026-09-30.

## Current state (why it's not ready)
- `User` has only `college_email` (a plain unique email) — **no structured college**.
- `MatchQueue` stores `intent` + `gender_preferences` — no college.
- `MatchmakingService._attempt_match` filters candidates by **`intent` only** +
  mutual gender preference (`_is_compatible`). No college scoping, and nothing
  parses the email domain.
- → A student from college A can match a student from college B today.

## Plan
1. **College identity.**
   - New `colleges` table: `id`, `code`, `display_name`, `allowed_email_domains`
     (list), `is_active`, optional per-college config/flags.
   - Add `college` FK on `User` (nullable until backfilled).
   - Resolve a user's college from their **verified email domain** via a
     domain→college map at onboarding/verification (table, not raw domain, because
     colleges often have several domains/subdomains). Reject sign-ups whose domain
     maps to no active college.
   - Tie to existing college-ID verification where useful.
2. **Scope matching.**
   - Add `college` to `MatchQueue` (denormalized for the hot query).
   - `_attempt_match`: `.filter(status=SEARCHING, college=user.college, intent=...)`.
   - Keep the mutual gender-preference check.
   - Update the queue index → `(status, college, intent, joined_queue_at)`.
3. **Thin-pool handling (important for small/new colleges).**
   - Per-college toggle for a cross-college fallback, or a "waiting for more people
     on your campus" state, so small colleges don't starve.
4. **Ops / analytics.**
   - Per-college feature flags + dashboards; admin can enable/disable a college.
   - Scope the lobby stats (active-range, intent counts) by college too.
5. **Migration.**
   - Add table + FK; backfill existing users' college from their email domain;
     backfill `MatchQueue.college`.

## Effort
Moderate, well-contained — matching is centralized in one service, so the change
is schema + migration + one filter + onboarding wiring + FE college display. Not a
rewrite.
