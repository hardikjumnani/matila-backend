# Relationship-exclusive chats (multi-chat for other intents) - Plan

## Goal
Change "one active chat per user" so it applies ONLY to **RELATIONSHIP** intent: a user
may have at most one active relationship chat, but **unlimited parallel FRIENDSHIP /
CASUAL chats**. Snapshot the matched intent on the chat so the rule is stable.

## Current state (grounding - it's smaller than it looks)
- The limit is enforced in application code only (no DB constraint), via **two guards**:
  1. Matchmaking join: `matchmaking_service.py:102` -> `has_open_anonymous_chat(user)` ->
     CONFLICT "already in an active chat".
  2. `ChatService.create_chat` defensive guard: `chat_service.py:215-220` (same check for
     both users).
- "Active" for matchmaking = **`MATCH_BLOCKING_STATUSES = (ACTIVE, EXTENDED, EXPIRED)`**
  (`chat_service.py:65`). **REVEALED does NOT block matchmaking** (deliberate, AI_BRIDGE
  [00056]) - a revealed chat already frees the slot. So the user's intuition is right.
- The `Chat` row has **no intent field**; matching is same-intent (`matchmaking_service.py:138`
  filters `intent=user.intent`), so a chat's intent = both participants' shared intent at
  match time, but it's never persisted.
- Chat is created in **one place**: `ChatService.create_chat` (`chat_service.py:204-242`),
  called only from `_attempt_match` (`matchmaking_service.py:152`).
- A user may have only one SEARCHING queue entry (`MatchQueue` unique index), so searches
  are sequential (one intent at a time).
- **Already multi-chat-safe**: the inbox `GET /chats` returns a list; chat serializers, the
  WS consumer, presence, unread counts, notifications, and all of reveal/decision are
  per-chat. No change needed there.
- Intent is set/changed via `PATCH /users/me` -> `AuthService.update_profile`
  (`auth_service.py:136`); changing it does NOT touch existing chats or the queue.

## Design decisions
- **Snapshot intent on the chat** (`Chat.matched_intent`), set at creation from the queue
  entry's intent. The exclusivity check keys off the CHAT's matched_intent, so it's stable
  when a user later edits their profile intent.
- The guard uses **both**: the user's CURRENT intent (what they're searching for) and the
  CHAT's matched_intent (what occupies the relationship slot). Block only
  `joining as RELATIONSHIP AND already has an open RELATIONSHIP chat`.
- **REVEALED keeps freeing the relationship slot** (owner's lean; = current behavior). The
  one-relationship rule applies to the MATCH_BLOCKING window (ACTIVE/EXTENDED/EXPIRED).

## Changes

### 1. `Chat.matched_intent` (new field + migration)
- Add `matched_intent = CharField(choices=Intent.choices, blank=True, default="")` to `Chat`
  (`apps/chats/models.py`). Index not required (lookups are via ChatParticipant join; add a
  composite index only if profiling needs it).
- Data migration backfill: set `matched_intent` for existing chats from a participant's
  current `user.intent` where determinable; where not, leave `""`. The guard treats
  `""` as RELATIONSHIP (conservative: an unknown legacy chat holds the slot, never
  accidentally allows a second relationship chat). Pre-launch prod has only test data, so
  the backfill is low-stakes.

### 2. `ChatService` - intent-aware queries + creation
- `create_chat(user_a, user_b, *, intent)` gains an `intent` param; the matcher passes
  `entry.intent` (the authoritative queue snapshot; both entries share it). Set
  `Chat.matched_intent=intent` on create (`chat_service.py:223-232`).
- New helper: `has_open_relationship_chat(user) -> bool` = a `ParticipantStatus.ACTIVE`
  participation whose `chat__status__in MATCH_BLOCKING_STATUSES` and
  `chat__matched_intent in (RELATIONSHIP, "")` (treat empty legacy as relationship).
- Defensive guard in `create_chat` (replace L215-220): block ONLY for a relationship chat:
  ```
  if intent == RELATIONSHIP and (has_open_relationship_chat(a) or has_open_relationship_chat(b)):
      return CONFLICT
  ```
  Non-relationship chats are never blocked (parallel allowed).

### 3. Matchmaking join guard (`matchmaking_service.py:102-103`)
Replace the unconditional block with:
```
if user.intent == Intent.RELATIONSHIP and self._chats.has_open_relationship_chat(user):
    return ServiceResult.fail("CONFLICT", "You can only have one relationship chat at a time.")
```
FRIENDSHIP/CASUAL joins are never blocked here.

### 4. Matchmaking `get_status` (`matchmaking_service.py:220-238`)
Today it returns MATCHED if the user has ANY open anonymous chat - which would mislabel a
FRIENDSHIP user who is in a chat AND still searching. Fix: **check the SEARCHING queue entry
FIRST**, then fall back to the "just matched" inference:
```
entry = searching entry
if entry: return SEARCHING (...)
open_chat = get_open_anonymous_chat(user)   # newest first
if open_chat: return {"state": "MATCHED", "chat_id": ...}
return IDLE
```
So a user who is actively searching reads SEARCHING even while in other chats; a waiter whose
queue entry was deleted on match still discovers the new chat (newest open-anonymous). Make
`get_open_anonymous_chat` return the newest such chat.

### 5. Lobby stats `busy_ids` (`matchmaking_service.py:277-298`)
Intent-scope the "busy" exclusion:
- viewer intent != RELATIONSHIP -> `busy_ids = empty` (friendship/casual users are always
  available for more).
- viewer intent == RELATIONSHIP -> busy = users with an open RELATIONSHIP chat
  (`chat__status__in MATCH_BLOCKING_STATUSES`, `chat__matched_intent in (RELATIONSHIP,"")`).
  (Drops REVEALED from the busy set, aligning with the join guard - a revealed-relationship
  user is available for a new relationship match.)

### 6. Admin (`management_views.py:70`, minor)
`AdminUserDetailView` returns a single `active_chat_id`. With parallel chats it shows one of
them. Low priority; options: keep (one representative), or return `active_chat_ids: [...]`.
Recommend adding `active_chat_ids` alongside the existing field to avoid a breaking change.

### Concurrency (why no DB constraint is needed)
A user's matches are serialized: `join` locks the user's own SEARCHING queue row
(`select_for_update`), and the matcher locks each candidate queue row with SKIP LOCKED and
deletes both on match. So one queue entry is consumed by one matcher at a time - a user
cannot be in two concurrent match transactions, so they cannot acquire two relationship
chats at once. The `create_chat` app guard (#2) is therefore sufficient; no partial unique
index on chats is added.

## What does NOT change (verified safe for multiple chats)
Inbox `GET /chats` (already a list), `ChatSerializer` (per-chat unread/other_participant/
masking), the WS consumer (scoped per chat_id), presence (per-user key - shared dot is fine),
notifications (per-chat payloads), reveal/decision/endgame (entirely chat-scoped),
onboarding, and the settings/profile path. No single-chat assumption exists in these.

## Edge cases / things to confirm
1. **Is FRIENDSHIP actually selectable?** Docs note FRIENDSHIP was hidden in the onboarding
   intent picker (`docs/REVEAL_FLOW_SPEC.md:18`, `docs/LOBBY_STATS_PLAN.md:46`) though the
   enum has RELATIONSHIP/FRIENDSHIP/CASUAL. If only RELATIONSHIP is live to users, this
   feature is a no-op until other intents are exposed. CONFIRM which intents the picker
   offers (FE/onboarding) - this gates the whole feature's usefulness.
2. **Sequential, not simultaneous, searches**: a user searches one intent at a time (one
   SEARCHING queue entry). Parallel friendship chats accumulate by searching friendship again
   after each match - acceptable and matches the single-profile-intent model. (If
   simultaneous multi-intent search is ever wanted, that's a bigger MatchQueue change.)
3. **Intent change mid-life**: handled by the matched_intent snapshot - an open relationship
   chat holds the slot even if the user flips their profile intent; flipping back and
   searching relationship is correctly blocked.
4. **REVEALED frees the slot** - confirm OK (current behavior; owner's lean).

## Tests
- Join: RELATIONSHIP user with an open relationship chat -> CONFLICT; FRIENDSHIP user with an
  open friendship (or relationship) chat -> allowed; RELATIONSHIP user with only a friendship
  chat -> allowed.
- create_chat: relationship pair where one has an open relationship chat -> fails (no match);
  friendship pair both already in friendship chats -> succeeds (parallel).
- matched_intent set correctly from the queue intent; stable after a profile intent change.
- get_status: searching-while-in-a-chat -> SEARCHING (not MATCHED); matched waiter -> MATCHED
  with the newest chat.
- lobby stats: friendship viewer not under-counted by busy users; relationship viewer excludes
  open-relationship users (but not revealed-relationship ones).
- Multiple parallel friendship chats for one user coexist; inbox lists them.
- Update/migration tests for matched_intent backfill.
- Existing matchmaking/chat tests that assume the unconditional block need updating.
- Plain `pytest` (`config.settings.test`).

## Rollout
One `chats` migration (add field) + a data backfill. All other changes are code. Additive and
backward-compatible (empty matched_intent treated as relationship). Ships in a normal deploy.
Coordinate with FE only if `get_status`/admin shape changes are surfaced (the SEARCHING-first
reorder is backward-compatible for the single-chat flows).

## Open decisions for the owner
1. REVEALED relationship chat frees the slot - **LOCKED: frees the slot** (not counted
   toward the one-relationship limit; = current behavior). 2026-10-23.
2. Admin `active_chat_id`: add `active_chat_ids` list (recommended) or leave one?
3. Confirm which intents are user-selectable today (gates the feature's reach).
