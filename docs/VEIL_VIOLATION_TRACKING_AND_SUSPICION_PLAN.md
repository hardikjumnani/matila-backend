# Veil - Violation Tracking + Second-hand Suspicion Engine - Plan

Two linked features on top of the existing Veil/Muffle trust-and-safety stack:

1. **Violation tracking** - a durable, per-person log of every policy violation,
   including ones the **frontend** blocks before they reach us.
2. **Suspicion engine ("second-hand Veil")** - a parallel, **non-blocking** scanner
   that notes sketchy-but-not-blockable behaviour (odd scripts, romanized-Indic
   code-mix, gibberish, obfuscation, near-miss leaks) for admin assessment. Never
   affects the user; purely an internal signal for admins + for tuning Veil.

Guiding rule (unchanged): Veil blocks ALL PII-reveal attempts while NEVER hindering
legitimate users (zero false positives wins conflicts). The suspicion layer must
NEVER block or alter a message - it only records.

---

## 0. What already exists (grounding)

- `LeakEvent` (`apps/privacy/models.py:27-64`, table `leak_events`): per-flagged-
  message record - user, chat, category, severity, action (ALLOW/BLOCK/ESCALATE),
  mode (shadow/enforce), rule_version, detectors(JSON), `raw_message` (raw text,
  "temporary" policy), matched_span, created_at. Indexed by (user,created_at),
  (chat,created_at), (category). Written ONLY by `VeilService._record_event`.
- `ProfanityEvent` (Muffle) - same shape, a precedent for a second engine with its
  own event table.
- `LeakStrike` (OneToOne user->count) - the single per-user violation aggregate;
  bumped by Veil enforce-blocks and Muffle T2 slurs; drives advisory escalation.
- `TrustSafetyService` (`apps/privacy/services/trust_safety_service.py`) - read-only
  aggregation (leak feed, profanity feed, offenders, per-user profile, stats) +
  `reset_strikes`. Backs `/admin/safety/*` (routes `apps/admin_panel/api/urls.py:156-182`,
  views `safety_views.py`, all `IsAdminUser`).
- Message send path `MessageService.send_text` (`apps/messaging/services/message_service.py:89-143`):
  fully **synchronous, inline, fail-open**. Veil at L113-116 (ANONYMOUS phase only),
  Muffle mask at L120-122, persist L134-140, broadcast on commit. No Celery in the
  send path.
- Reports app (`apps/reports/`) - users report each other; `ReportService.resolve`
  maps `ResolutionAction` -> account status (SUSPENDED/BANNED). Admin-driven.
- **No auto-escalation today**: strikes never change `account_status` automatically;
  Veil escalation only writes an audit row + sends a warning notification. Account
  actions are always a human admin (direct) or a human resolving a report.
- Audit: `AuditService.log(actor_type, action, entity_type, entity_id, metadata)`;
  dotted actions (`veil.escalated`, `safety.strikes_reset`); SYSTEM actor for
  automated safety events, ADMIN actor for admin actions.
- Flags: `FeatureFlagKey` + `FEATURE_FLAG_DEFAULTS`; tunables in `AppConfigKey` +
  `APP_CONFIG_DEFAULTS` (+ optional validator). Read via `ConfigurationService`.

### Research notes that shaped the design
- Romanized Hindi/Telugu/Tamil has **no standard spelling**, so ML language-ID is
  unreliable and heavy; a deterministic function-word lexicon (Veil already ships
  multilingual romanized keyword sets) is the right tool for a *soft* signal, not a
  precise classifier. [Hinglish LI, arXiv 2107.01202; Nature s41599-024-03058-6]
- Gibberish is best caught by a tiny **character-level Markov** bigram/trigram model
  scored against a threshold (cheap, deterministic, no heavy deps). [Renaud/grepler
  gibberish-detector]
- Shadow-moderation practice: never block, assign a **risk score**, route a middle
  band to human review, **weight by account history**, keep it tunable, and do NOT
  auto-action low-confidence flags. [ModerationAPI allow/review/reject; ActiveScore;
  Safety-Flag calibration study]. This is exactly the advisory model below.

---

## PART 1 - Violation tracking (incl. frontend-blocked)

### 1.1 Problem
Today only **backend** Veil blocks are recorded (as `LeakEvent`). Violations the
**frontend** stops client-side never reach us, so a user who repeatedly tries to
leak but is caught by the app's own client guard leaves no trace. We want one
per-person violation log that includes those.

### 1.2 Data model change - a `source` discriminator on `LeakEvent`
Add one field (additive migration, safe default):
- `source` CharField(choices `ViolationSource` = `BACKEND` | `FRONTEND`, default
  `BACKEND`, db_index). New `ViolationSource` enum in `apps/privacy/enums.py`.

Rationale: a frontend-blocked attempt is the *same shape* as a backend block
(category + text + optional matched span), so reuse `LeakEvent` + the existing admin
leak feed/serializer rather than a parallel table. Admin can filter by `source`.

### 1.3 New client endpoint - FE reports what it blocked
`POST /api/v1/privacy/violations` (new `apps/privacy/api/`), `IsAuthenticated`.
Body (all client-supplied, treated as **untrusted**):
```
{ "category": "<LeakCategory or 'OTHER'>",    // coerced; unknown -> PLATFORM/OTHER
  "attempted_text": "<string, <=4000>",
  "chat_id": "<uuid, optional>",               // validated: caller must be a participant
  "client_detectors": ["<freeform rule ids>"], // what the FE rule matched
  "occurred_at": "<iso8601, optional>" }
```
Service `ViolationReportService.record_frontend(user, ...)`:
- Writes a `LeakEvent` with `source=FRONTEND`, `action=BLOCK`, `mode="frontend"`,
  `rule_version="fe"`, `detectors=client_detectors`, `raw_message=attempted_text`,
  category coerced to the enum (unknown -> a safe default).
- **Counts as a violation (owner decision):** bumps `LeakStrike` and feeds the
  per-user log exactly like a backend block. The client is spoofable, so this is
  guarded by the per-user rate limit + text cap below, and every FE report is tagged
  `source=FRONTEND` so an admin can always distinguish it from a backend-verified
  block. It still never auto-suspends - escalation stays advisory (decision 4).
- Guards: `chat_id` (if given) must belong to the caller; `attempted_text` capped;
  category coerced; **per-user rate limit** (e.g. 60/min via DRF throttle) to stop a
  buggy/malicious client flooding the table; `user_id` is ALWAYS the authenticated
  user (never client-supplied).
- Audit: `actor_type=USER, action="violation.frontend_reported", entity_type="user",
  entity_id=user.id, metadata={category, source:"frontend"}`.

### 1.4 Admin surface
- `TrustSafetyService.leak_events(...)` gains a `source` filter; the existing
  `/admin/safety/leak-events` view + serializer expose `source` and already expose
  `raw_message`. `user_safety` + `offenders` break counts down by source so an admin
  sees "FE-blocked vs BE-blocked" per user.
- No new endpoint strictly required for Part 1 (reuses the leak feed), just the
  `source` field + filter + serializer field.

### 1.5 Privacy / retention (owner decision: keep forever)
`raw_message` (and `attempted_text`) store the **exact PII users tried to leak**
(phone numbers, emails). Owner decision: **retain raw violation text indefinitely**,
no purge/redaction task. This is consistent with how chat text already works - message
`text_content` rows are never deleted either (only 7-day media purge; user delete is a
soft `is_deleted` flag). Guardrails that stay:
- **Access**: admin-only (already gated via `IsAdminUser`); raw-text reads are
  auditable. The "temporary: store raw for admin review" comment on
  `LeakEvent.raw_message` (`veil_service.py:201`) becomes the intended permanent
  behaviour.
- No `VIOLATION_RAW_RETENTION_DAYS`, no `purge_violation_text` task.

---

## PART 2 - Suspicion engine ("second-hand Veil")

A parallel, non-blocking layer that records **soft signals** and a per-user
**suspicion score** for admins. Part of Veil, separate records, never blocks.

### 2.1 New pure scanner - `SuspicionGuard`
`apps/privacy/services/suspicion_guard.py`, mirrors `LeakGuard`: pure, deterministic,
no DB/network. `scan(text, sender_name="", leak_verdict=None) -> SuspicionVerdict`
returning a list of `SuspicionSignal(signal, weight, span)`. Reuses `normalize.py`
views and `ruleset` dictionaries. Initial signals (all tunable, extensible):

1. **`NON_LATIN_SCRIPT`** - characters in non-Latin Unicode blocks (Devanagari
   U+0900-097F, Bengali, Gurmukhi, Gujarati, Tamil U+0B80-0BFF, Telugu U+0C00-0C7F,
   Kannada, Malayalam, Oriya, Arabic, CJK...). Deterministic range check. **Low
   weight** - many legit users type their native script; fire mainly on script
   *mixing* within a message or above a small proportion. Tunable.
2. **`ROMANIZED_INDIC` (code-mix)** - romanized Indic function words in Latin text,
   from a lexicon: reuse Veil's multilingual sets + a dedicated romanized-stopword
   list ("hai/hain/kya/nahi/mera/tera/bhej/kar/milte/chalo/yaar/kaise/kahan/kab",
   romanized Tamil/Telugu markers "enna/epdi/da/nuvvu/ra/cheyi"...). Weight scales
   with hit density. **Low-medium weight.**
3. **`GIBBERISH`** - character-level Markov bigram log-probability vs a small
   pre-trained English model shipped as a data asset (`apps/privacy/data/
   gibberish_model.json`), plus cheap heuristics (5+ consonants no vowel, very low
   vowel ratio, keyboard-adjacency runs). Allowlist common chat tokens (lol/brb/idk/
   hmm/omg/haha) to curb FP. **Low weight** (noisiest). Threshold in config.
4. **`OBFUSCATION`** - "normalization did a lot of work": zero-width chars present,
   confusables substituted (CONFUSABLES_TABLE changed the string), heavy leet,
   excessive intra-word separators ("h.e.l.l.o", "a d d m e"). Computed by diffing
   `raw` vs `fold_primary`/`collapse_all`. **Medium weight** - strong evasion tell.
5. **`NEAR_MISS`** - sub-threshold leak observations Veil deliberately does NOT block
   (to stay zero-FP), surfaced here instead: 6+ consecutive digits under the phone
   floor; a platform word with no steer verb; invite+time with no place (the
   "milte hain" class); an edit-distance-1 near-match to a structured-PII needle.
   **Medium weight** - this is the highest-value signal for *improving Veil*: it
   watches exactly the borderlines we chose not to block. (Implementation: a light
   `near_miss_signals()` hook on `LeakGuard`, or recompute a few cheaply here.)

Scoring: each signal has a weight from a config map; `SuspicionVerdict.score` = sum.
A per-message `SUSPICION_MIN_RECORD_WEIGHT` floor avoids recording trivial noise.

### 2.2 New models
- **`SuspicionEvent`** (`apps/privacy/models.py`, table `suspicion_events`), same
  `UUIDModel` shape as `LeakEvent`/`ProfanityEvent`: user FK, chat FK(nullable),
  `signals` JSON (list of {signal, weight, span}), `score` Pos int, `rule_version`,
  `raw_message` (retention-governed like Part 1.5), created_at; indexes
  (user,created_at), (chat,created_at).
- **`UserSuspicionProfile`** (OneToOne user, table `user_suspicion_profiles`):
  `score` (cumulative, optionally time-decayed), `event_count`, `last_event_at`,
  `review_status` (`SuspicionReviewStatus` = UNREVIEWED | REVIEWED | CLEARED |
  ACTIONED, default UNREVIEWED), `reviewed_by`, `reviewed_at`, `notes`. This is the
  per-person suspicion aggregate + the admin's assessment state.

### 2.3 New service - `SuspicionService`
Mirrors `VeilService`/`MuffleService`. `inspect(chat, sender, text, leak_verdict)`:
- Gated by `FeatureFlagKey.SUSPICION_ENABLED`; fail-open (never breaks messaging).
- Runs `SuspicionGuard.scan`; if `score >= SUSPICION_MIN_RECORD_WEIGHT`, writes a
  `SuspicionEvent` and updates `UserSuspicionProfile` (score += , count ++, resets
  `review_status` to UNREVIEWED if it was CLEARED and new signals arrive).
- **Returns nothing actionable** - the caller ignores the result. Never blocks,
  never masks, never notifies the user.
- Audit (optional, low-volume): `actor_type=SYSTEM, action="suspicion.raised"` only
  when a profile crosses a configurable attention threshold (avoid audit spam).

### 2.4 Hook point (sync vs async)
Call `SuspicionService.inspect(...)` in `MessageService.send_text`, right after Veil
**allows** the message (so it only scans messages that actually send), on the
original `content` (pre-Muffle-mask).

Two placement options:
- **(A) Synchronous inline** (recommended) - same as Veil/Muffle, wrapped so any
  error is swallowed. The scan is deterministic and cheap (range checks + lexicon +
  a tiny Markov), comparable to the Muffle pass already there. Keeps raw PII off the
  Redis broker and keeps the code simple. Adds a small, bounded latency.
- **(B) Async via Celery** (scale option) - after commit, dispatch
  `scan_suspicion.delay(chat_id, user_id, content)` (matila-celery is running). Zero
  send-latency impact, but passes raw text through the broker (PII hop) and adds a
  task. Switch to this only if profiling shows (A) adds meaningful latency.

Start with (A); the service boundary makes moving to (B) a one-line change.

### 2.5 Admin integration
Extend `TrustSafetyService` + `/admin/safety/*` following the existing pattern:
- `suspicion_events(user_id, chat_id, signal, min_score)` reader -> `GET
  /admin/safety/suspicion-events` (cursor-paginated, new serializer).
- `suspicion_offenders(min_score, review_status)` -> `GET
  /admin/safety/suspicion-offenders` (top-N by score, like `offenders`).
- `user_safety` augmented with suspicion score + review_status + recent timeline;
  `stats` augmented with suspicion counts (24h/7d, by signal).
- **Admin assessment action** (the "mark it / act" ask): `POST
  /admin/safety/users/{id}/suspicion/review` with body `ReviewActionSerializer`
  (status + notes) -> sets `UserSuspicionProfile.review_status`/`reviewed_by`/
  `reviewed_at`/`notes`, audits `safety.suspicion_reviewed`. Admin can CLEAR
  (benign), mark REVIEWED, or ACTIONED - and separately use the existing
  suspend/ban/report-resolve flows to actually act. No automatic account action
  (consistent with today's advisory-only escalation; an auto-escalation bridge would
  be a separate, explicit decision).
- Leak feed gains the `source` filter from Part 1.

### 2.6 Config / flags
- `FeatureFlagKey.SUSPICION_ENABLED` (default **False** - seeded off, tuned in
  shadow, then enabled; same rollout as payments/reveal). ONE master flag for the
  whole subsystem (not per-signal), consistent with Veil's "no per-decoder flags".
- `AppConfigKey` tunables (admin-editable, no deploy): `SUSPICION_SIGNAL_WEIGHTS`
  (JSON map signal->weight), `SUSPICION_GIBBERISH_THRESHOLD`,
  `SUSPICION_MIN_RECORD_WEIGHT`, `SUSPICION_ATTENTION_SCORE` (audit/notify threshold).
  Add validators in `apps/configuration/validators.py`. (No retention config - raw
  violation text is kept forever per the owner decision.)

### 2.7 Frontend + AdminPanel contracts (bridge - only after your go)
- **AI_BRIDGE (frontend)**: the `POST /privacy/violations` schema + when to call it
  (whenever the client guard blocks), and optionally passing device/keyboard locale
  as extra suspicion context.
- **EXTERNAL_BRIDGE (AdminPanel)**: a `source` column on the violations view; a new
  Suspicion feed; per-user suspicion score + review_status + timeline; the
  "mark reviewed / clear / actioned" control; wire to the new endpoints.
- Per standing rule, I will NOT post to any bridge until you explicitly say so; the
  messages are drafted and held.

---

## Migrations
`apps/privacy/migrations/0003_*`:
- add `LeakEvent.source` (default BACKEND, indexed) - safe additive;
- create `SuspicionEvent`, `UserSuspicionProfile`.
Plus `apps/configuration` seed update for the new flag/config defaults
(`seed_runtime_config`).

## Testing
- `SuspicionGuard` unit tests per signal (deterministic), plus a **benign "noise
  budget" corpus**: ordinary chat (typos, casual Hinglish, native-script greetings,
  emoji) must produce a low aggregate score so the admin feed stays usable. Because
  suspicion never blocks, some FP is tolerable - but admin noise is the cost to
  control.
- FE-report endpoint: auth, participant check, category coercion, rate-limit,
  `source=FRONTEND`, **no strike bump**, cannot set another user_id.
- Admin suspicion feed/offenders/review action + audit rows.
- FE-reported violation bumps the strike counter (decision 3) and is tagged
  `source=FRONTEND`.
- Regression: Veil/Muffle/`send_text` behaviour and latency unchanged; suspicion
  disabled flag = zero new rows.
- Run with plain `pytest` (`config.settings.test`).

## Phasing
- **Phase 1 - Violation tracking**: `LeakEvent.source`, FE-report endpoint + service,
  admin `source` filter/serializer, retention task + config. Self-contained, ships
  first, immediate value.
- **Phase 2 - Suspicion core**: `SuspicionGuard` (script, romanized-indic,
  obfuscation, near-miss), `SuspicionEvent` + `UserSuspicionProfile`,
  `SuspicionService` hooked into `send_text` (sync), admin feed + score + review
  action, `SUSPICION_ENABLED` seeded OFF, shadow-tune.
- **Phase 3 - Gibberish + tuning**: ship the Markov asset, add `GIBBERISH`, corpus
  tuning, enable the flag; optional time-decay scoring; optional (explicit-decision)
  auto-escalation bridge from sustained suspicion -> admin queue priority or account
  action.

## Follow-up changes from AdminPanel review (owner decisions 2026-10-23, A0006)

1. **Scrub violation raw text on erase (keep event + score).** In
   `UserErasureService.erase` (atomic block), for the erased user: clear
   `LeakEvent.raw_message` + `matched_span`; `ProfanityEvent.raw_message` +
   `masked_message` + `words`; `SuspicionEvent.raw_message` + `signals` (keep
   `top_signal` + `score`). Leave `UserSuspicionProfile` untouched. Add
   `leak_events_scrubbed` / `profanity_events_scrubbed` / `suspicion_events_scrubbed`
   counts to the erase summary + audit metadata. Rows + scores survive; the leaked
   text is gone (reconciles "keep forever" with right-to-erasure). No migration.
2. **Admin chat transcript endpoint.** New `GET /api/v1/admin/chats/{chat_id}/messages`
   (admin-gated), `AdminChatMessagesView` in `safety_views.py` + a route. Mirrors
   report-detail: `Message.objects.filter(chat_id=...).order_by("created_at")` via the
   existing `AdminMessageSerializer`. Response `{chat_id, status, participant_ids,
   messages[]}`; 404 if chat missing; full chronological list (paging can be added
   later). No migration.
3. **suspicion-offenders paging:** keep `offset` + `limit` (no `total`). No change.

All three are additive, no migration; fold into the same deploy. Then finalize bridge
B0013 items 8 (scrub-on-erase) and 9 (transcript endpoint) and post after owner go.

## Owner decisions (LOCKED 2026-10-23)
1. Suspicion scan: **A - synchronous inline.**
2. Raw violation text: **kept forever**, no purge/redaction (consistent with chat
   text, which is also never deleted).
3. FE-reported violations: **count as real violations** (bump the strike counter),
   tagged `source=FRONTEND`; guarded by rate limit + text cap since the client is
   spoofable. Still no auto-suspend (see 4).
4. Accumulated suspicion: **admin-only**, no automatic account action (matches
   today's advisory-only escalation).
