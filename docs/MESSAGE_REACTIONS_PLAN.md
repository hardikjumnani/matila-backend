# Message Reactions (emoji reactions on chat bubbles) - BE Plan

## Report
Frontend built React-to-message (AI_BRIDGE [00066]) against an ASSUMED contract and
needs the backend half (today a reaction POSTs -> 404 -> rolls back). Owner-locked UX:
one reaction **per user per message** (re-tap same emoji = remove, different = replace),
emoji set **backend-owned + runtime-editable** (like the verification gesture), FE
bundles a default of 6: `❤️ 😂 😮 😢 👍 🔥`. Fixed emoji set, no free text, so **no
Veil/anti-leakage concern**.

Decision: **confirm the FE's assumed contract as-is** (paths/bodies/WS events/serializer
field) so there is zero FE rework; the only open product choices are below.

## Grounding (how the messaging layer already works)
- `Message` (`apps/messaging/models.py`), `related_name` on chat = `messages`; soft
  delete only; `build_message_payload` (`realtime.py`) builds the WS frame, mirrored by
  `MessageSerializer` (`api/serializers.py`) for history.
- Broadcasts: `broadcast_to_chat(chat_id, event, payload)` (`apps/common/realtime.py`),
  called inside `transaction.on_commit`. Precedent: `soft_delete` emits
  `message.deleted {message_id}`; `_broadcast_new_message` emits `message.new {message}`.
- The consumer's `chat_broadcast` handler (`apps/chats/consumers.py:149`) forwards ANY
  `{event, payload}` generically -> **new event names need NO consumer change**. Reactions
  are REST (POST/DELETE), not client->server WS events, so `receive_json` is untouched too.
- Writability: `ChatService.is_writable(chat)` = status in WRITABLE_STATUSES
  (ACTIVE/EXTENDED/REVEALED). `is_participant(chat, user)` for membership.
- Runtime-editable config pattern: `AppConfigKey.GESTURE_POOL` default + validator
  (`apps/configuration/validators.py`) + served to the client via `GET /config`
  (`ConfigurationService.get_runtime_config`).

## Data model
New `MessageReaction` (`apps/messaging/models.py`, table `message_reactions`, `UUIDModel`):
- `message` FK -> messaging.Message, CASCADE, related_name `reactions`.
- `user` FK -> users.User, CASCADE, related_name `message_reactions`.
- `emoji` CharField(max_length=16).
- `created_at` DateTimeField(auto_now_add).
- **UniqueConstraint(message, user)** -> enforces one-per-user; a replace is an UPDATE of
  the existing row. Index on (message).
- Migration: `apps/messaging/migrations/00xx_messagereaction`.

## Config (runtime-editable emoji set)
- `AppConfigKey.REACTION_EMOJIS` + `APP_CONFIG_DEFAULTS` = `["❤️","😂","😮","😢","👍","🔥"]`
  (matches the FE bundled default).
- Validator in `apps/configuration/validators.py`: non-empty list, each a non-blank short
  string, de-duplicated, max ~12. Wired into `AdminAppConfigUpdateView` (already generic),
  so admins edit it at runtime with no deploy.
- Expose to clients in `get_runtime_config()` as
  `"reactions": {"version": "<hash8>", "emojis": [...]}` where `version` = a short stable
  hash of the emoji list (changes when the admin edits it) - satisfies the FE's
  `{version, emojis}` shape. (No separate endpoint needed; it rides the existing `/config`
  the app already fetches on start.)

## API (confirming the FE contract)
New `MessageReactionView` (APIView, IsAuthenticated) at
`POST|DELETE /api/v1/messages/{message_id}/reactions`; route added in
`apps/messaging/api/urls.py` BEFORE the bare `messages/<uuid:message_id>` delete route
(first-match wins, same as the existing `/view` route).
- **POST** body `{ "emoji": "<one of the active set>" }` -> upsert the caller's reaction
  (replaces any existing). 200 with `{ message_id, user_id, emoji, reactions: [...] }`.
- **DELETE** -> remove the caller's reaction (idempotent: 200 even if none existed),
  `{ message_id, user_id, reactions: [...] }`.
- New serializer `SetReactionSerializer { emoji }`.

Service methods on `MessageService`:
- `set_reaction(*, message_id, user, emoji)` and `remove_reaction(*, message_id, user)`:
  1. load message -> `RESOURCE_NOT_FOUND` if missing or `is_deleted` (no reacting to a
     deleted bubble).
  2. `is_participant(chat, user)` -> `FORBIDDEN` if not (any participant may react, to
     their own and the partner's messages - not sender-only, unlike delete).
  3. `is_writable(chat)` -> `CHAT_READ_ONLY` if not (see Open choice 1).
  4. POST only: `emoji in ConfigurationService().get_config(REACTION_EMOJIS)` else
     `INVALID_REACTION` (400).
  5. `MessageReaction.objects.update_or_create(message, user, defaults={emoji})` /
     `.filter(...).delete()`.
  6. `transaction.on_commit` -> broadcast (below).
- Add `INVALID_REACTION -> 400` to `ERROR_STATUS_MAP` (`apps/common/responses.py`).

## Serializer / payload (the `reactions[]` field)
Add `reactions: [{ user_id, emoji }]` to BOTH:
- `MessageSerializer` (GET `/chats/{id}/messages` history) - a method field reading
  `message.reactions`. **Returns `[]` for a soft-deleted message** (reactions hidden like
  its text/media). `ChatMessagesView` queryset gains `.prefetch_related("reactions")` to
  avoid N+1.
- `build_message_payload` (the `message.new` WS frame) - include `reactions` (empty `[]`
  for a brand-new message, and `[]` for a deleted one) so history + new frames share one
  shape; FE reconciles by `(message_id, user_id)`.

## WebSocket events
Broadcast to the chat group on commit (both participants; actor included, same as
`message.new`; FE reconcile is idempotent):
- `reaction.added` -> `{ message_id, user_id, emoji }` (a replace emits one `reaction.added`).
- `reaction.removed` -> `{ message_id, user_id }`.
No consumer change (generic `chat_broadcast`).

## Veil / anti-leakage
None. Fixed, server-validated emoji set, no free text -> nothing to scan. (Confirmed w/ FE.)

## Also-affected parts (cross-cutting)
1. **Erasure.** `UserErasureService.erase` must also delete the erased user's reactions,
   matching how it deletes their other authored activity (messages, ratings_given) and the
   just-shipped scrub policy. Add `MessageReaction.objects.filter(user=user).delete()` in
   the atomic block, with a `reactions_deleted` count in the summary + audit metadata.
   (Reactions ON the user's own messages already cascade when those messages are
   hard-deleted; this line removes the ones they left on the partner's surviving messages,
   which otherwise linger pointing at the anonymized user.)
2. **Deleted messages.** Covered in Serializer/payload above: a soft-deleted message
   reports `reactions: []` (hidden like its text/media). Existing rows are left in the DB
   but not surfaced; reacting to a deleted message is already rejected in the service.
3. **Admin evidence.** Add `reactions: [{user_id, emoji}]` to `AdminMessageSerializer`
   (`apps/admin_panel/api/serializers.py`) so the report-detail transcript and the new
   `GET /admin/chats/{chat_id}/messages` show reactions as moderation evidence (admins see
   them even on deleted messages, unlike the user-facing serializer).

## Tests
- Model/service: set creates; re-POST same emoji by same user = still one row (replace);
  different emoji = replace (one row); DELETE removes; partner can react to sender's msg;
  non-participant -> FORBIDDEN; non-writable chat -> CHAT_READ_ONLY; emoji outside set ->
  INVALID_REACTION; deleted message -> RESOURCE_NOT_FOUND; one-per-user uniqueness.
- API: POST/DELETE happy paths + the error codes above; auth required.
- Serializer/payload: history + `message.new` carry `reactions[]`; prefetch (no N+1);
  a soft-deleted message reports `reactions: []`.
- Config: `/config` exposes `reactions.emojis`; admin PUT validates (reject empty / bad).
- Erasure: erasing a user deletes their reactions (incl. ones on the partner's surviving
  messages) and returns `reactions_deleted` in the summary.
- Admin evidence: `AdminMessageSerializer` (report detail + chat transcript) includes
  `reactions[]`, present even on deleted messages.
- Run with plain `pytest` (`config.settings.test`).

## Rollout
Additive; one new table (one migration). Ships with the next deploy alongside the
suspicion/violation work. **Dependency for live two-way sync:** the prod `/ws/` upgrade
must be healthy ([00064]); reactions ride the same per-chat socket. REST set/remove works
regardless; only the real-time echo needs the socket. (That is an nginx/ops item, separate
from this feature code.)

Then reply on AI_BRIDGE confirming items 1-3 of [00066] verbatim + the Open-choice answers.

## Open choices (my recommendations)
1. **Writable-only?** Recommend reactions only while the chat is writable
   (ACTIVE/EXTENDED/REVEALED) -> `CHAT_READ_ONLY` on ENDED/EXPIRED, matching message
   sending. Alternative: allow reacting to history in read-only chats (more lenient). FE
   left this to us.
2. **Reaction-set endpoint:** serve it inside the existing `GET /config` (recommended, no
   new endpoint) vs a dedicated `GET /reactions/set`. FE said this is a nice-to-have and
   will use its bundled default until present, so `/config` is enough.
3. **System messages:** allow reactions on SYSTEM messages (reveal/extend dividers) or
   restrict to TEXT/IMAGE bubbles. Recommend restrict to non-SYSTEM (FE reacts to bubbles).
