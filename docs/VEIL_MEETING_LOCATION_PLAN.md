# Veil hardening: real-world meet-ups & location leaks (zero-FP)

Status: PLAN ONLY (no code). 2026-11-01.
Source case: prod chat `7fd42fe0` (Ujjwal x Yash, ANONYMOUS). Veil blocked the
phone, but a full in-person rendezvous slipped through:
`Lets meet in Goa` / `Baga beach` / `Lets meet at bells resort at dinner` /
`Uniworld 1` / `Let's meet 5th flor`.

## 1. Why it slipped (today's mechanics)

MEETING fires on PRESENCE of signal pairs in the message/window:
`INVITE + DESTINATION`, `INVITE + DIRECTIONS`, `DIRECTIONS + DESTINATION`, or a
standalone `LOCATION_PIN` (see `_meeting_blocks`). Two causes:
1. **Destination lexicon too small.** `resort`, `beach`, `Baga beach`,
   `Uniworld`, floor/tower/flat words are not DESTINATION tokens, so the invite
   never paired with a place.
2. **Precision allowance.** We deliberately allow `INVITE + TIME` with no
   recognised place (so "let's meet tomorrow" / "kal milte hain" do not FP).
   `bells resort at dinner` landed in that allowed bucket.

Core difficulty: separating "let's meet AT <place> [at <time>]" (block) from
"I love Goa" / "the beach was nice" / "which floor do you stay on" (allow).
Simply enlarging the DESTINATION lexicon under the current PRESENCE model would
false-positive, especially via the 8-message window (an invite in msg 1 + a
casual place word in msg 5 would pair). So coverage must come from TIGHTER
coupling, not broader presence.

## 2. Principle

Keep Veil's bar: hard-block only validator-certain rendezvous; route everything
FP-risky to the admin-only suspicion engine. Ship the new meeting rules in
SHADOW mode first (meeting is the FP-riskiest category), review logged would-be
blocks, then flip to enforce.

---

## 3. Veil hard-block additions (zero-FP)

### 3.1 Venue lexicon + INVITE PROXIMITY (not presence)
- Add a curated, multilingual VENUE set to DESTINATION: resort, hotel, cafe,
  restaurant, mall, beach, club, pub, bar, lounge, station, metro, bus stand,
  airport, cinema/theatre, park, hostel, pg, cafe names generic only (no brands),
  etc.
- Block only when an INVITE token sits within a TIGHT token window of the venue
  (e.g. <= 4 tokens) OR is joined to it by a locational preposition
  (`at|in|to|near|outside|behind|inside|opp/opposite` + venue). "meet at the
  resort", "aa jao station", "come to the cafe" -> block. "the resort was nice"
  / "I love the beach" (no invite nearby) -> allow.
- This mirrors the existing ASK/STEER proximity model, which is already FP-safe.

### 3.2 Locational-preposition + place coupling
- Pattern: INVITE ... `(at|in|on|to|near|outside|behind|opp)` <venue OR
  address-component OR capitalised proper-noun run>. The preposition is what
  turns a mention into a rendezvous. Still requires the INVITE nearby, so a bare
  "I'm at the resort" status does not trip.

### 3.3 Structured LOCATION_PIN (standalone, format-distinctive, like phone/email)
These are distinctive enough to block alone, zero-FP by construction:
- Map URLs: `maps.google.*`, `goo.gl/maps`, `maps.app.goo.gl`, `g.co/maps`,
  `openstreetmap`, `what3words` (confirm the URL detector already catches generic
  map links; add the shorteners/w3w explicitly if not).
- Geo-coordinates: `lat, long` decimal pairs in a plausible range.
- Google Plus Codes (e.g. `7JWV+2M`), `what3words` triplets (`word.word.word`
  pattern gated to the w3w shape).

### 3.4 Address components, INVITE-coupled only
- Tokens: floor/flat/room/block/sector/gate/tower/plot/`h.no`/wing/lane + a
  number ("5th floor", "flat 302", "block C", "gate 3", "tower 2").
- Standalone these are innocent ("the office is on the 5th floor"), so block
  ONLY when invite-coupled (3.1/3.2 proximity). Otherwise -> suspicion (4.2).

### 3.5 Multi-message / rolling-window handling (revised)
The attack is often split across messages ("lets meet in goa" -> "baga beach" ->
"bells resort" -> "5th flor"), so the rolling window (last N sent messages) must
participate. Three tiers, decreasing certainty:

1. **Self-contained completing message (hard block, works in a stream):** if the
   message that completes a sequence is itself invite + venue/address in one
   clause ("lets meet at bells resort at dinner", "let's meet 5th flor"), or a
   standalone pin / map link / full address, it blocks on its own. The window is
   not even needed; a stream that ends in such a message is caught.
2. **Split invite + place via the window (hard block, SHADOW-FIRST):** invite in a
   recent window message + an **actionable place** in the completing message,
   where "actionable" means a locational-preposition-governed venue
   (`at|to|in|near + venue`), an address-component with a number, or a pin. The
   place's own specificity (preposition / number / pin), not mere co-presence, is
   the FP gate, and the invite must be an explicit rendezvous invite. Because a
   split invite+place is inherently less certain than a single clause (e.g.
   "let's meet up" ... "I was at the cafe"), this tier ships in **shadow mode
   first**, we review logged would-be blocks on real chats, and only flip to
   enforce if it is clean.
3. **Weak accumulation (suspicion, never auto-block):** scattered place hints, a
   bare city, or several venues building a picture across the chat without a clean
   invite+place pairing -> admin-only suspicion signal. Auto-blocking this would
   false-positive on normal getting-to-know-you chat (hostel/year/city exchange),
   which is NOT a leak.

---

## 4. Suspicion engine (admin-only, non-blocking)

For the forms that cannot be hard-blocked without FP:
1. **City / landmark gazetteer** (Goa, Baga beach, named localities): soft
   signal, weighted higher when near an invite/preposition but below the
   hard-block bar.
2. **Venue / address component WITHOUT a nearby invite** ("Uniworld 1",
   "5th floor" on their own): soft signal.
3. **Vague / future meet-up** ("let's meet in Goa someday", invite + city, no
   pin): soft signal.
4. **Behavioral thread**: a conversation accumulating multiple place +
   invite signals across messages (exactly this chat's shape) raises the user's
   priority tier for admin review, even if no single message hard-blocks.

---

## 5. Muffle (profanity) side-note, parallel

Harassment slipped in masked-evasion form (`S3x`, `ga*du`). Not a Veil leak, but
the same chat shows it. Fix: apply Veil-style normalization (leet fold
`3->e 1->i 0->o 4->a 5->s`, strip internal punctuation / zero-width) before the
Muffle profanity lexicon match, so `S3x`, `g@@ndu`, `ga*du` are masked. Masking
(not blocking) means FP cost is low, but keep it tight. Separate workstream.

---

## 6. Honest limit

A determined user describing a place purely in prose ("the big resort near the
blue gate, 8pm") with no venue keyword, preposition, pin, or invite token will
still pass a zero-FP detector. That residual is by design handed to the
suspicion engine + human review, never force-blocked.

## 7. Validation / rollout

- Corpus adds: real rendezvous (block) incl. the exact chat lines; casual place
  talk / status-at-place / "which floor" question (allow); map link + coords +
  plus code (block).
- Zero-FP corpus gate (`test_corpus.py`) must stay green.
- Ship MEETING changes in SHADOW first, review logged hits, then ENFORCE.
- Bump `RULESET_VERSION`.

## 8. Recommendation (priority order)

1. 3.3 structured LOCATION_PIN (cleanest, zero-FP, immediate).
2. 3.1/3.2 venue lexicon + invite proximity (the main gap; shadow-first).
3. 3.4 invite-coupled address components.
4. Suspicion signals (Section 4) for the residual.
5. Muffle normalization (Section 5) as a parallel profanity task.
