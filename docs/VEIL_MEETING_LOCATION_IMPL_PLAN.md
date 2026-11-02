# Veil meeting/location hardening: final implementation plan

Status: IMPLEMENTED + TESTED (local), 2026-11-01. Not yet deployed.
Tier 2: multi-message window is an ENFORCED, tightly gated hard block (proximity +
completer-shape + completion-is-new), not shadow. Design + zero-FP rationale in 3A.

Shipped (local, 684 tests green incl. the zero-FP corpus):
- Lexicons: venue words (languages.py); address/pin regexes + Gate-4 word sets
  (leakguard.py); RULESET_VERSION -> 2026.11.01-v2.5.
- Single message: structured-pin + full-address standalone; INVITE + preposition-
  governed venue (proximity, not presence); INVITE + address-component; fuzzy-venue
  fallback only when no clean positioned venue exists.
- Window: `_meeting_window` with the four gates (detector tag `meeting_window`).
- Enforcement: `FeatureFlagKey.VEIL_MEETING_WINDOW_ENFORCE` (default True) kill-switch
  in VeilService (OFF -> shadow LeakEvent + allow; scoped to the window hit only).
- Tier 3: MEETING_SOFT (pii) / LOCATION_SOFT (ambient) suspicion signals.
Note: proximity is a module constant in the pure scanner (not runtime config), so
`VEIL_MEETING_PROXIMITY` from section 4 was intentionally NOT added. The FE pre-send
mirror gets the new venue words (ruleset export) but NOT the regex pin/address/window
detectors, which are backend-only (backend stays authoritative).
Scope: catch real-world rendezvous + location leaks, zero-FP, single- AND
multi-message. Excludes profanity/Muffle (separate). Supersedes the sketch in
docs/VEIL_MEETING_LOCATION_PLAN.md (that doc holds the rationale; this is the
build spec).

Driving case: chat `7fd42fe0` ("Lets meet at bells resort at dinner" / "Baga
beach" / "Uniworld 1" / "Let's meet 5th flor"). Non-goal: harmless
getting-to-know narrowing (hostel/year/city, chat `e04e2083`) must stay allowed.

## 0. Current mechanics (what we build on)

- `LeakGuard._signal_scan` already records positions for dictionary signals in
  `prim_pos[...]` (INVITE / DESTINATION / TIME / DIRECTIONS live there) and uses
  `_near(prim_pos[a], prim_pos[b], dist)` for ASK/STEER proximity.
- Meeting today is PRESENCE-based: `meet = {s in _MEETING_SIGNALS if s in
  any_present}` -> `_meeting_blocks(meet)` (INVITE+DESTINATION, INVITE+DIRECTIONS,
  DIRECTIONS+DESTINATION, or standalone LOCATION_PIN).
- Cross-message: `scan()` runs `_block_categories(prior_text + " " + raw)` when
  the current message didn't already block, emitting a `Hit(cat, HIGH, "window",
  …)` for any new blocking category in the window.
- `_URL_RE` already matches generic URLs.

## 1. Lexicons / patterns (apps/privacy/dictionaries.py, languages.py, ruleset.py)

1a. **INVITE (explicit rendezvous only)** — tighten/confirm: "lets meet", "meet
me", "meet up", "come to", "come over", "see you at", "reach", "catch up at";
romanized: "aa jao", "aajao", "milte hain", "chalte hain", "aa ja". Casual "meet"
without these stays non-INVITE.

1b. **VENUE (new DESTINATION entries, multilingual):** resort, hotel, cafe,
restaurant, dhaba, mess, canteen, mall, beach, club, pub, bar, lounge, station,
metro, "bus stand", airport, cinema, theatre, park, hostel, pg, library, gate,
block, tower, wing. Curated; no brand names.

1c. **ADDRESS-COMPONENT (new regex, with a number):**
`\b(flat|room|plot|tower|block|gate|wing|sector|house|h\.?\s*no|shop)\s*#?\s*\d+`
and `\b\d+\s*(st|nd|rd|th)?\s*(floor|flr|manzil)\b`.

1d. **STRUCTURED PIN (new, standalone-blockable like phone/email):**
   - map URLs: `maps.google`, `maps.app.goo.gl`, `goo.gl/maps`, `g.co/maps`,
     `openstreetmap`, `osm.org` (extend `_URL_RE` or a dedicated `_MAP_URL_RE`);
   - geo-coordinates: decimal `lat, long` in plausible ranges;
   - Google Plus Code: `\b[23456789CFGHJMPQRVWX]{4,8}\+[23456789CFGHJMPQRVWX]{2,}\b`;
   - what3words: `///w.w.w` or a gated `word.word.word` triplet.

## 2. Detection (apps/privacy/services/leakguard.py)

2a. **Switch meeting venue to PROXIMITY, not presence.** Add
`_INVITE_VENUE_DIST` (~6 tokens). Block MEETING when
`_near(prim_pos["INVITE"], prim_pos["DESTINATION"], _INVITE_VENUE_DIST)` OR an
INVITE is joined to a VENUE by a locational preposition (`at|in|to|near|outside|
behind|opp` + venue). Keep the existing LOCATION_PIN and DIRECTIONS+DESTINATION
rules unchanged.

2b. **ADDRESS-component:** INVITE-coupled only (same proximity rule) -> MEETING.
Standalone address component alone does NOT hard-block (-> suspicion), EXCEPT a
full multi-part address ("flat 302 tower 2") which is actionable on its own.

2c. **STRUCTURED PIN:** standalone MEETING/LOCATION_PIN hit in `_detect`
(format-distinctive, zero-FP), independent of invite or message count.

2d. **Detector tags for the gate:** single-message/self-contained meeting hits
use detector `meeting`; the cross-message split hits (from the window path) must
be distinguishable. Tag the window-sourced meeting hit `meeting_window` (instead
of the generic `window`) so VeilService can gate it (section 3).

## 3. Tiered enforcement + shadow-first (apps/privacy/services/veil_service.py,
   apps/configuration)

Three tiers by certainty (matches the rationale doc):

- **Tier 1 (enforce now):** self-contained completing message (INVITE+venue/
  address in one clause) + all STRUCTURED PINs + full addresses. High certainty,
  works inside a multi-message stream because the completing message is enough.
- **Tier 2 (multi-message window, ENFORCED hard block, tightly gated):** the
  rendezvous split across the sender's own messages. Detected over the
  concatenated window stream by PROXIMITY + an actionable-place requirement + a
  completer-shape whitelist + a completion-is-new test, NOT presence. Zero-FP by
  construction; full design and per-gate justification in section 3A. Emits
  detector tag `meeting_window`. Kept behind a config kill-switch
  `AppConfigKey.VEIL_MEETING_WINDOW_ENFORCE` (default True) so it can be flipped
  to log-only instantly if prod ever surfaces an FP. Global `VEIL_MODE` untouched.
- **Tier 3 (suspicion, never auto-block):** weak accumulation (scattered place
  hints, bare city, venues with no clean invite pairing). Emit a suspicion signal
  (new `MEETING_SOFT` / `LOCATION_SOFT` in apps/privacy/suspicion_data.py +
  suspicion_guard) so it surfaces to admins only. Keeps harmless hostel/year/city
  narrowing out of the block path.

## 3A. Tier 2 deep-dive: zero-FP multi-message hard block

Real-code context: the window (`VeilService._build_window`) is the SENDER's own
last N sent text messages, concatenated chronologically with single spaces (no
partner text is ever in it). `LeakGuard.scan` runs the window path only when the
current message did not already block, and today uses a PRESENCE diff
(`_block_categories(prior+raw) - _block_categories(prior)`). Presence is what
makes a bigger venue lexicon false-positive: an INVITE in msg 1 pairs with a
casual place word in msg 5.

The fix is to stop asking "do an invite and a place both APPEAR in the window"
and ask "is a rendezvous being COMPLETED right now, tightly". Four gates, each
with its own zero-FP justification; ALL must hold (pins and full addresses are
the standalone exception, below).

### Gate 1: proximity, not presence
Over the concatenated stream's `fold_primary` token view, reuse the existing
`prim_pos` position map and `_near(...)`. Require an explicit INVITE position
within `_INVITE_PLACE_DIST` (default 4) tokens of an actionable PLACE position.
Token distance IS the cross-message adjacency measure: messages are joined with
one space, so the last token of msg A and the first of msg B are distance 1,
while an invite in msg 1 and a place in msg 5 are tens of tokens apart and fall
out. Proximity therefore does two jobs at once, for free: (a) it reassembles a
unit split across a message boundary ("...5th" | "floor"), and (b) it rejects the
distant-pairing FP. This is the ASK/STEER proximity model that is already FP-safe
in prod, applied to meeting.

### Gate 2: completion is NEW (the leak is delivered now)
At least one half of the pair (INVITE or PLACE, whichever lands last) must lie in
the CURRENT message: its token offset >= the current-message start offset (=
count of `fold_primary` tokens in `prior_text`). This stops re-blocking a pair
already fully present in history and anchors the block to the message just sent.
The split "...5th" (prior) + "floor" (now) passes because the reassembled address
span ends inside the current message.

### Gate 3: actionable PLACE only
A place counts only if it is one of:
  - a VENUE token governed by a locational preposition
    (`at|to|in|near|outside|behind|opp|opposite|beside` + venue),
  - an ADDRESS COMPONENT WITH A NUMBER ("5th floor", "flat 302", "tower 2"),
  - a FULL multi-part address, or
  - a STRUCTURED PIN (map URL, geo-coords, plus code, what3words).
A BARE venue or city with no preposition/number/pin is NOT actionable here; it
routes to Tier 3 suspicion. That is why "I love goa", "the beach was nice" and
"which hostel / Uniworld 1" never window-block. Structured pins and full
addresses are actionable STANDALONE (format-distinctive), so for THEM Gates 1 and
4 are waived: a pin or full address split across two messages reassembles in the
stream (Gate 2) and blocks on its own.

### Gate 4: completer-SHAPE whitelist (kills the "I was at the cafe" FP)
The hardest FP is invite + a status clause:
  "let's meet up"  +  "I was at the cafe"   -> MUST ALLOW
  "let's meet up"  +  "at the cafe"         -> MUST BLOCK
The preposition phrase "at the cafe" is identical in both; the only signal is
whether the current message is an independent status clause or a bare locational
fragment. So we gate on a POSITIVE whitelist of completer shapes, blocking only
when the current message IS essentially the fragment:
  - (C1) starts with optional short filler (ok/sure/yeah/haan/thik/...) then a
    locational preposition + place, with NO subject+verb before the preposition;
  - (C2) a short (<= 4 token) place-only fragment: venue/address/number/article
    tokens only, no finite verb;
  - (C3) is or contains a structured pin, address-with-number, or full address.
A message that begins with subject pronoun + finite verb ("I was ...", "we went
...", "it's ...") fails C1 and C2 and never window-blocks. Because this is a
POSITIVE whitelist, any shape we fail to enumerate UNDER-blocks (routes to
suspicion) and can never create an FP. This property is what lets Tier 2 enforce
rather than only shadow.

### Char-level splitting (collapsed view)
Word-level splits ("5th" | "floor", "bells" | "resort") are already adjacent in
the spaced concatenation, so the normal regex/`prim_pos` view handles them.
Character-level splits ("f" | "l" | "a" | "t" | "3" | "0" | "2") need the
separator-free view: run ONLY the format-distinctive, digit/format-anchored
patterns (structured pins, coords, plus codes, address-with-number) over
`collapse_base(stream)`, never the bare venue-word list (gluing arbitrary words
risks FP). This mirrors the self-name Tier 2/Tier 4 collapsed-view approach
already shipped in `_self_name`.

### The one honest correction to the "5th / floor" example
Reassembling "5th" + "floor" into "5th floor" is necessary so enter-key splitting
cannot beat the detector, but "5th floor" ON ITS OWN still must not hard-block,
because it is exactly the benign "the office is on the 5th floor". After
reassembly it obeys the same coupling rule as a single message: invite nearby
(Gates 1/4) -> block; no invite -> Tier 3 suspicion. Reassembly closes the
evasion; coupling keeps it zero-FP. (So the pure "5th" | "floor" two-message case
with no invite is ALLOWED by design; it blocks only once an invite joins it.)

### Implementation surface (what actually changes)
In `LeakGuard.scan`, replace the MEETING part of the window path (the lines that
emit `Hit(cat, HIGH, "window", ...)`) with a dedicated `_meeting_window(...)` that:
builds `prim_pos` + offsets over `fold_primary(prior_text + " " + raw)`; applies
Gates 1-4; runs the collapsed-view pins/address pass; and emits
`Hit(MEETING, HIGH, "meeting_window", span)` only when a gate set is satisfied.
Non-meeting categories keep the existing presence-diff window behaviour. VeilService
reads `VEIL_MEETING_WINDOW_ENFORCE`; when False it records the `meeting_window`
hit as a shadow `LeakEvent` and allows (log-only), when True it blocks normally.

## 4. Config (apps/configuration/constants.py, validators.py, seed)

- `VEIL_MEETING_WINDOW_ENFORCE` (bool, default True): Tier-2 kill-switch. True =
  enforce the `meeting_window` hard block; False = log the hit as a shadow
  `LeakEvent` and allow (instant revert path if an FP ever shows up).
- `VEIL_MEETING_PROXIMITY` (int, default 4): `_INVITE_PLACE_DIST`, the window
  proximity in tokens (Gate 1). Kept tight; tunable without a deploy.
- Add suspicion weights for the new soft signals to DEFAULT_SIGNAL_WEIGHTS
  (ambient/structural class so they don't over-rank legit users).
- Seed only the NEW keys in prod (the full seed overwrites tuned values).

## 5. Tests (apps/privacy/tests/)

Hard-block (enforce): "lets meet at bells resort at dinner", "let's meet 5th
flor", "meet me at the cafe", "aa jao station", a map link, "19.0760, 72.8777",
a plus code, "flat 302 tower 2".
Allow (zero-FP gate): "I love Goa", "the beach was nice", "which hostel? /
Uniworld 1", "which year are you / 2029", "the office is on the 5th floor",
"let's meet up sometime" (invite, no place), "I was at the cafe earlier" (status).
Cross-message (Tier 2) matrix, one assertion per synthetic chat (each `|` is a
separate sender message; partner messages are not in the window):
  BLOCK:
    - "meet me" | "at bells resort"              (G1 near, G2 now, G3 prep+venue, G4 C1)
    - "lets meet" | "5th" | "floor"              (address reassembled, invite-coupled)
    - "come over" | "flat 302" | "tower 2"       (full address reassembled)
    - "aa jao" | "station"                       (romanized invite + venue)
    - "lets meet" | "at the cafe near the mall"  (prep+venue fragment completer)
    - "maps.app.goo.gl/" | "xY7q2"               (pin reassembled, standalone)
    - "19.0760," | "72.8777"                     (coords reassembled, standalone)
    - "f" | "l" | "a" | "t" | "3" | "0" | "2"    (char-split address, collapsed view) + invite
  ALLOW (zero-FP gate):
    - "let's meet up" | "I was at the cafe"       (G4: status clause, not a fragment)
    - "which hostel" | "Uniworld 1"              (bare venue answer -> suspicion)
    - "the office is on the" | "5th floor"       (reassembles, no invite -> suspicion)
    - "I love goa" | "the beaches are amazing"   (no invite; bare city/venue)
    - "let's meet up" | "sometime next week"     (invite + time, no place)
    - "did you meet" | "your friend at the cafe" ("meet" transitive, not INVITE)
    - "lets catch up" | "I loved bells resort btw" (G4: status clause)
The two load-bearing probes: "let's meet up" + "I was at the cafe" (ALLOW) is the
Gate-4 proof; "lets meet" + "5th" + "floor" (BLOCK) is the reassembly proof.
Corpus: add the benign place-talk lines to `test_corpus.py`; gate stays green.
Bump `RULESET_VERSION`.

## 6. Rollout

1. Ship Tier 1 + structured pins + Tier 2 (`meeting_window`) ENFORCING by default
   (`VEIL_MEETING_WINDOW_ENFORCE=True`), Tier 3 suspicion signals on (admin-only).
   The four gates make Tier 2 zero-FP by construction, so it ships enforcing.
2. Deploy (code-only unless suspicion weights need seeding; no model migration).
   Seed ONLY the new keys on prod (the full seed overwrites tuned values).
3. Optional safety bake: flip `VEIL_MEETING_WINDOW_ENFORCE=False` for the first
   few days to watch `meeting_window` as shadow `LeakEvent`s on real chats, then
   flip True. Recommended if we want eyes on prod traffic before enforcing.
4. Kill-switch: if any FP ever surfaces, set the flag False to drop to log-only
   instantly, no deploy.

## 7. Honest limit

A pure-prose meetup with no venue keyword, preposition, number, or pin ("the big
place near the blue gate, 8ish") still passes a zero-FP detector by design, and
goes to suspicion/human review, never a forced block.
