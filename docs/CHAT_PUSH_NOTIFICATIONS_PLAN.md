# Chat push notifications: new message + reaction

Status: PLAN ONLY (no code). 2026-11-02.
Goal: when the other person sends a message or reacts, push a phone notification to
the recipient. Identity-safe (anonymous app), non-blocking, and not noisy.

## 0. What already exists (reuse, do not rebuild)
- `firebase.send_push(tokens, *, title, body, data) -> PushResult` (success/failure
  counts + dead `invalid_tokens`). `FirebaseNotConfigured` is a clean skip.
- `DeviceTokenService`: `register`, `deactivate_tokens`, `active_tokens_for(user)`.
  FCM token storage + rotation is done; FE already has a register endpoint.
- `send_push_notification` Celery task: the row-based path for INBOX notifications
  (reveal, verification, violations) via `NotificationService.create_notification`.
- Presence: the chat consumer writes `presence_key(user_id)` to cache on connect /
  heartbeat (TTL) and deletes on disconnect. `cache.get(presence_key(uid))` = online.
- Aliases: `anonymous_alias(chat_id, user_id)` is a stable, storage-free, identity-
  safe label ("Azure Seal") per (chat, user).
- Hook points in `MessageService`: `send_text` / `send_image` (after
  `_broadcast_new_message`), and `set_reaction` (after `_broadcast_reaction`). Both
  already use `transaction.on_commit` for side effects.

So the work is: a push-only delivery path (no inbox row) + event wiring + noise control.

## 1. Principles
1. **Identity-safe.** The push NEVER carries the other user's real name or the
   message text. Use the sender's per-chat ALIAS for the label and generic copy for
   the body. This holds in every phase (safest), not just ANONYMOUS.
2. **No inbox spam.** Messages/reactions are NOT written to the `notifications`
   table (the chat + its `unread_count` is the source of truth; the alerts inbox is
   for account events). This feature is push-only.
3. **Non-blocking, fail-open, post-commit.** Delivery is enqueued on
   `transaction.on_commit` and never affects the send path (mirrors broadcast).
4. **Quiet.** Suppress when the recipient is already in the chat; coalesce rapid
   messages; collapse on the device so one chat = one notification.

## 2. Delivery path (push-only, no Notification row)
New Celery task `push_chat_event` in `apps/notifications/tasks/` that mirrors
`send_push_notification` but takes an ad-hoc payload instead of a Notification row:

    push_chat_event(recipient_id, *, kind, chat_id, title, body, data)
      - if not flag CHAT_PUSH_ENABLED: return
      - if recipient is present in THIS chat (section 5a): return (skip)
      - if throttled for (chat, recipient, kind) (section 5b): return (skip)
      - tokens = DeviceTokenService().active_tokens_for(recipient); none -> return
      - firebase.send_push(tokens, title, body, data)  (FirebaseNotConfigured -> skip)
      - deactivate invalid_tokens; set the throttle marker on success

A thin `ChatPushService` (apps/notifications/services/chat_push_service.py) builds
the payload and enqueues the task on commit:

    notify_new_message(message)        # recipients = chat participants - sender
    notify_reaction(message, reactor, emoji)   # recipient = message.sender (author)

Recipient resolution: add `ChatService.other_participant_ids(chat, exclude_user_id)`
(ChatParticipant filter excluding the actor); 2-person today but keep it a list.

## 3. Triggers + wiring
- **Text message** -> `MessageService.send_text`, after `_broadcast_new_message`:
  `self._push.notify_new_message(message)`. (Veil-blocked sends already return
  early, so a blocked message never notifies.)
- **Image message** -> `send_image`, same spot. Body: generic (see 4).
- **Reaction** -> `set_reaction`, after the broadcast. Notify ONLY the message
  author, and only when `reactor_id != message.sender_id`. No push on
  `remove_reaction`. An emoji change still routes through `set_reaction` but the
  throttle (5b) dedupes rapid toggles.
- **System messages** (`create_system_message`: reveal/extend dividers) -> NO chat
  push here. Reveal/expiry pushes, if wanted, are a separate account-event task.

## 4. Content (identity-safe) + payload
- Label (title): the sender's alias, `anonymous_alias(chat_id, sender_id)`
  ("Azure Seal"). Identity-safe by construction.
- Body: generic, NO message text / NO emoji-with-text leak risk on a lock screen:
  - message: "sent you a message"  (image: "sent a photo")
  - reaction: `f"reacted {emoji} to your message"` (emoji only, no text)
- Data payload (strings; drives routing + client foreground suppression + dedup):
  `{ "type": "chat.message" | "chat.reaction", "chat_id": <id>,
     "message_id": <id>, "alias": <alias> }`
  Client taps -> open that chat. If the app is foregrounded ON that chat, the client
  suppresses the banner (defense-in-depth with 5a).
- Device coalescing: pass an Android collapse key / notification tag = `chat-<id>`
  so a newer message REPLACES the older banner (one notification per chat). Requires
  a small `send_push` enhancement to accept `collapse_key` (optional param;
  `messaging.AndroidConfig(collapse_key=..., notification=AndroidNotification(tag=...))`).

## 5. Noise control
### 5a. Presence suppression (don't ping someone already reading the chat)
`presence_key(user_id)` is per-USER (online in SOME chat), too coarse to prove the
recipient is in THIS chat. Add a per-chat presence key the consumer already can
write cheaply: `chat_presence_key(chat_id, user_id)` set on connect/heartbeat (TTL)
and deleted on disconnect, alongside the existing per-user key. The task skips the
push when `cache.get(chat_presence_key(chat_id, recipient_id))` is set.
(Fallback if we skip the consumer change: rely only on client-side foreground
suppression via the data payload. Recommended: do the per-chat key, it is ~5 lines.)

### 5b. Throttle / cooldown (coalesce rapid sends)
Per `(chat_id, recipient_id, kind)` cooldown in cache: send at most one push per
`CHAT_PUSH_COOLDOWN_SECONDS` (default ~45s). Because the body is generic ("sent you
a message"), coalescing needs no content accuracy; opening the chat shows everything.
Reactions get their own (longer) cooldown so a burst of reactions is one ping.

### 5c. Device collapse key (section 4) stacks with 5b so the shade stays clean.

## 6. Config / flags (apps/configuration/constants.py)
- `FeatureFlagKey.CHAT_PUSH_ENABLED` (default True): master kill-switch.
- `FeatureFlagKey.CHAT_REACTION_PUSH_ENABLED` (default True): reactions can be
  silenced independently (they are the noisier, lower-value signal).
- `AppConfigKey.CHAT_PUSH_COOLDOWN_SECONDS` (default 45).
- `AppConfigKey.CHAT_REACTION_PUSH_COOLDOWN_SECONDS` (default 120).
Seed only the new keys on prod (never the full seed).

## 7. Mute (optional, phase 2)
No per-chat mute exists today. If wanted: `ChatParticipant.muted` (bool) + a
PATCH endpoint; the task skips a muted recipient. Left out of the MVP; the plan is
mute-ready (the recipient filter is the single place to add the check).

## 8. Edge cases
- Veil-blocked message -> no row created -> no push (automatic).
- Muffle-masked text -> body is generic, so no leak either way.
- Sender never notified of their own message; reactor never notified of their own
  reaction.
- Chat ended / not writable -> sends already rejected upstream -> no push.
- No active device tokens -> task skips (SKIPPED path already exists).
- Firebase not configured (dev) -> skip, no retry (existing behaviour).
- Dead tokens -> deactivated from the push result (existing behaviour).

## 9. Tests
- `MessageService.send_text` / `send_image` enqueue `notify_new_message` for the
  OTHER participant only (mock ChatPushService / assert the on_commit call).
- `set_reaction` notifies the message author, not the reactor; `remove_reaction`
  does not; self-reaction does not.
- Task: throttle (2nd within cooldown skipped), presence suppression (recipient in
  chat -> skipped), no-tokens skip, dead-token deactivation, flag off -> no-op.
- Identity-safety: push title == alias, body has no real name and no message text.
- Veil-blocked send -> no push.

## 10. Rollout
- Backend ships behind `CHAT_PUSH_ENABLED` (default True). Code + two config keys;
  one tiny consumer change (per-chat presence key) and one `send_push` param
  (collapse key). No model migration unless phase-2 mute is included.
- FE needs (bridge, when owner approves): register device token (endpoint exists),
  handle the `data` payload to route to the chat, and suppress the banner when
  foregrounded on that chat. Confirm Android notification channel + icon.

## 11. Decisions to confirm
- D1. Body stays GENERIC (no message text preview) in all phases? (Recommended: yes,
  privacy-first; a text preview could be a later per-user setting.)
- D2. Reaction pushes ON by default (throttled), or OFF until asked? (Recommended:
  ON, behind its own flag.)
- D3. Add the per-chat presence key for server-side suppression (recommended), or
  rely on client-side foreground suppression only for the MVP?
