# Per-user block list (block by name string) - Plan

## Goal
Let a user keep a personal block list of **bare name strings** (first / last / full names)
in app settings. During matchmaking, anyone whose name matches an entry on the list is
filtered out as one more compatibility step. No user lookup / no "does this person exist"
reveal - purely string matching against candidates' names at match time. Spelling mistakes
and over/under-blocking are accepted by design (the privacy trade-off vs. a real user search).

Example: a user adds "Himanshu" -> every Himanshu in their match pool is skipped.

## Design decisions
- **Name strings only**, never a user search. The blocker never learns if a name is on the
  app; the filter just silently removes matches. (This is the whole point - a lookup would
  leak presence.)
- **Mutual / bidirectional**: when pairing A and C, block the pair if **A's list matches C's
  name OR C's list matches A's name**. Otherwise A could still be matched as the *candidate*
  of C's search. Checked both ways at match time.
- **Match rule = token-subset, normalized.** Normalize both sides (lowercase, strip accents
  via `normalize.strip_accents`, split on non-alphanumeric). A list entry matches a candidate
  iff **every token of the entry is present in the candidate's name tokens**:
  - "himanshu" (1 token) -> matches any name containing the token `himanshu` (first or last).
  - "himanshu chauhan" (2 tokens) -> matches only a name with BOTH tokens (a specific person).
  Token equality (not substring), so "himanshu" does not match "himanshuda". Broad vs narrow
  is the user's choice.
- Accepted limitations (documented, intended): spelling variants slip through; a common token
  over-blocks. Fine - the alternative (user search) breaks anonymity.

## Storage
Add `match_block_names = JSONField(default=list, blank=True)` to `User` (mirrors
`gender_preferences`). Store the user's trimmed raw entries (for display in settings);
normalize only at compare time. One migration (default `[]`, no backfill).
- Alternative considered: a separate `BlockedName(user, name, created_at)` table (cleaner
  per-row add/delete + admin/audit). Rejected for v1 - the list is small, per-user, read
  whole at match time; a JSON list matches the existing `gender_preferences` pattern and the
  "edit the list, save" settings UX. Revisit if per-entry metadata is ever needed.

### Validation / caps (in the serializer)
- list of strings; each trimmed; drop blanks; de-duplicate (case-insensitive).
- max **100** entries per user; each entry max **50** chars. Reject over-cap with
  `VALIDATION_ERROR`.

## API (settings)
- **Read**: add `match_block_names` to `UserSerializer` (so `GET /users/me` / session returns
  the current list for the settings screen).
- **Update**: add `match_block_names` to `UserProfileUpdateSerializer` (a `ListField` of
  `CharField`) so `PATCH /users/me` replaces the whole list. The FE settings screen manages
  the list (add/delete rows, or a newline-separated textarea it splits into the list) and
  sends the full array on save - simplest, matches `gender_preferences`.
  - Service: in `AuthService.update_profile`, add
    `if match_block_names is not None: user.match_block_names = <normalized-trim-dedupe>; update_fields.append(...)`.
  - Note: the existing pre-launch edit lock in `update_profile` applies (editable once
    onboarded and the college has launched) - consistent with other profile edits.
- (Optional) dedicated `POST/DELETE /users/me/block-names` for per-item ops - not needed for
  v1 if the FE sends the full list.

## Matchmaking integration (`apps/matchmaking/services/matchmaking_service.py`)
- Add a helper `_name_blocked(blocker, target) -> bool`: any normalized entry in
  `blocker.match_block_names` is a token-subset of `target.full_name`'s tokens.
- In **`_is_compatible(user, entry, candidate)`** add:
  `and not self._name_blocked(user, candidate.user) and not self._name_blocked(candidate.user, user)`
  so the pair is rejected if either side blocked the other's name. Runs in Python over the
  already-small candidate set (same place mutual gender/age checks run) - no SQL change.
- In **`get_lobby_stats`** apply the same mutual name-block filter to the online candidate
  set so `compatible_online` reflects the exclusion.
- No change to the SQL candidate query (name-token matching isn't SQL-friendly and the
  Python pass already exists for compatibility).

## Edge cases
- Empty list -> no effect (fast path: skip if `not match_block_names`).
- Candidate with blank `full_name` (not yet named / anonymized) -> no tokens -> never matches
  a block entry -> not blocked by name.
- Blocking your own name -> irrelevant (can't match self).
- Accents: "José" on the list blocks "Jose" and vice-versa (shared `strip_accents`).
- Large lists bounded by the 100-entry cap so match-time cost stays trivial.

## Admin (optional)
Expose `match_block_names` on the admin user detail (`AdminUserSerializer`) for support
visibility. Low priority.

## Tests
- Normalization/match: first-name blocks any match; full-name blocks only the exact pair;
  case + accent insensitivity; token equality (no substring over-match).
- Mutual directionality: A blocks "Himanshu" -> A+Himanshu never pair whether A or Himanshu
  initiates.
- Empty list = no effect; unrelated names still match.
- `get_lobby_stats` excludes name-blocked users from the count.
- PATCH validation: trim, dedupe, blank-drop, over-cap (100 / 50 chars) rejected.
- Plain `pytest`.

## Migration / rollout
One `users` migration (add `match_block_names`, default `[]`). Additive, backward-compatible,
no data backfill. Code-only matchmaking + serializer changes. Ships in a normal deploy; FE
settings screen is an AI_BRIDGE coordination item (the `match_block_names` field + PATCH
contract) after the backend lands.

## Open decisions for the owner
1. Storage: **JSON list on User** (recommended) vs a separate `BlockedName` table?
2. Match granularity: **token-subset** (recommended - first name blocks all, full name blocks
   one) - confirm this is the behavior you want.
3. Directionality: **mutual** (recommended - the pair never forms either way) vs one-way?
4. Caps: **100 names / 50 chars each** - OK?
