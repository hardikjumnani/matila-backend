# Lobby stats (online + intent counts) — plan (approved, parked)

> Status: **approved, not yet built.** Agreed 2026-09-30. Build when we pick it up.
> Shows social-proof numbers: online counts near slide-to-match, and per-intent
> counts at onboarding. All numbers shown as **"N+" ranges** (floor to nearest 10).

## 0. Range format (everywhere)
Round the real count **down to the nearest 10** and label it **"N+"**:
`{ "floor": 20, "label": "20+" }` (so 27 → "20+"). Hides exact counts, avoids
flicker. `floor: 0` → label `"0+"` (FE can render "just you / be the first").

## 1. Prerequisite — global presence signal (net-new)
No reliable "app online" signal exists today (`last_active_at` is written only on
`/auth/session`; WS presence is per-chat). Add one:
- **`POST /presence/heartbeat`** (authenticated), pinged by the app ~every 45s while
  foregrounded. Writes to a Redis **sorted set** `presence:online` →
  `ZADD <now_epoch> <user_id>`.
- "Online" = members with score ≥ `now − 90s`. Count via `ZCOUNT`; the online-ID
  set via `ZRANGEBYSCORE` (needed for the compatible filter). Periodic prune
  (`ZREMRANGEBYSCORE 0 now−90`) on read or a small Celery task.
- Rationale: live, no DB write per heartbeat, scalable, and yields the online-ID set.

## 2. `GET /matchmaking/lobby-stats` (near slide-to-match)
Returns two "N+" ranges for the authenticated user:
- **`total_online`** — `ZCOUNT(presence:online, now−90s, +inf)`.
- **`compatible_online`** — of those online, the ones this user can match with:
  verified + active + onboarded, **same intent**, **mutual gender compat**
  (`their gender ∈ my prefs` AND `my gender ∈ their prefs`), **not me**, and **not
  already in an active chat**.
  - Impl: online IDs from Redis → one `User` query
    (`id__in=online_ids, intent=me.intent, gender__in=me.prefs,
    gender_preferences__contains=[me.gender]`, status filters, exclude self +
    active-chat participants) → count → floor.
- Cache ~20s per (intent, gender, prefs) signature. Retire the old queue-only
  `/matchmaking/active-range`.

## 3. `GET /matchmaking/intent-stats` (onboarding)
- One grouped query: verified + active + onboarded users **per intent** →
  each as an "N+" range. Cache ~60s.
- Returns **all three intents** (see §4): e.g.
  `{ "RELATIONSHIP": {"floor":40,"label":"40+"},
     "FRIENDSHIP": {"floor":10,"label":"10+"},
     "CASUAL": {"floor":20,"label":"20+"} }`.

## 4. Bring back FRIENDSHIP intent
Reverses the earlier hide. Re-add `FRIENDSHIP` to `Intent` (enum + migration), and
un-hide it in the onboarding picker (FE) and the profile-update serializer choices.
Matchmaking already hard-filters by `intent`, so Friendship users match Friendship
users automatically. Counters then cover all three.

## 5. Multi-college
When [[multi-college-plan]] lands, both stats endpoints get an additional
`college = me.college` filter so numbers are per-campus.

## Decisions (locked)
- Friendship: back as a selectable intent; counters for all 3.
- Ranges: floor-to-10 "N+" format.
- Compatible-online excludes users already in a chat (unavailable).
- Heartbeat ~45s; online window ~90s (tunable).
- Buckets of 10.
