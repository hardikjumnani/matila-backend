# Veil + Suspicion - two-engine plan

> Status: PLAN ONLY (2026-10-26, rev 2). No code changed. Plan for improving BOTH
> engines, with a strict division of labor:
> - **Veil (the "whale" / anti-leakage engine):** the strong, solid engine. Blocks
>   automatically, in-line, during the anonymous phase. Only strict, specific,
>   validator-certain cases. Zero false positives is the hard constraint. Its
>   upgrades are the hard forms in `VEIL_HARDENING_30_HACKS_PLAN.md`.
> - **Suspicion engine ("second-hand Veil"):** BACKEND-ONLY, ADMIN-ONLY. It
>   accumulates soft signals for the near-miss / ambiguous variants that Veil cannot
>   block without causing false positives. It NEVER blocks, never masks, never
>   notifies the user, and has NO frontend presence. It affects a user only if an
>   admin reviews the accumulation and decides to act manually.

## The locked decision stands (no change)

`VEIL_VIOLATION_TRACKING_AND_SUSPICION_PLAN.md` owner decision #4 remains LOCKED:
accumulated suspicion is admin-only, with NO automatic account action and no
frontend effect. An earlier draft of this doc proposed "confidence-adaptive
blocking" (suspicion lowering Veil's threshold for flagged users). That idea is
DROPPED. Suspicion does not feed back into Veil's blocking at all. The only thing
that ever auto-blocks a message is Veil, on a validator-certain match.

## 1. The flow of this plan

For every PII-leak technique there is a spectrum:

- The blatant, unambiguous form -> **Veil hard-blocks it** (certain, zero FP).
- The partial, ambiguous, or disguised-but-plausible-innocent forms -> **would cause
  false positives if Veil blocked them**, so they go to the **suspicion engine** as
  soft signals that accumulate in the backend for admin review.

So the work is two-directional:
1. Keep and, where possible, extend Veil's hard cases (section 2).
2. For each of those cases, branch out every adjacent variant that still leaks PII
   but cannot be hard-blocked without false positives, and route it to suspicion
   (section 4, the bulk of the new work).

The guiding question for section 4 is the owner's: "all the ways a person could leak
their PII that would also increase false positives, so they are good for the
suspicion engine to hold in the backend."

## 2. Veil (whale) - the hard cases (keep + extend)

The approved list is `VEIL_HARDENING_30_HACKS_PLAN.md`. Veil blocks only when a
validator guarantees near-zero FP. The highest-value hard additions:

- Phase 0: gate every text surface (so no field bypasses Veil), strip all
  invisible/bidi/confusable characters before matching, apply the un-applied MEETING
  precision fix (removes a live false positive), reversed-digit phone.
- Phase 1: reversed self-name (6+ chars), name split across messages (collapsed to
  6+), spelled-digit reassembly across the window, leet-to-digit that validates as a
  full mobile, contextual romanized digits inside a validated phone, letters-only
  handle with tight proximity (shadow-tested first), platform abbreviation paired
  with an explicit ask.

Rule for Veil, unchanged: a hard rule ships only with new BENIGN and MALICIOUS rows
in `apps/privacy/tests/test_corpus.py`, and the corpus stays green. If a case cannot
be made zero-FP, it does NOT go into Veil. It goes to suspicion (section 4).

## 3. Suspicion engine - what it is and how it scores (backend, admin-only)

The suspicion engine is the home for everything in section 4. It is purely an
accumulator and an admin lens.

### 3.1 Signal taxonomy (classed and weighted)

Today there are 5 flat signals. Replace with a CLASSED taxonomy. The class is what
keeps the admin queue meaningful and keeps normal users off it.

**Ambient class** (normal behavior for this user base; down-weighted; capped;
VISIBILITY-ONLY, excluded from the review-priority score):
- `NON_LATIN_SCRIPT` (1)
- `ROMANIZED_INDIC` (1) - the whole user base romanizes Hindi; this alone must never
  push anyone up the queue.
- `GIBBERISH` (2)

**Structural class** (obfuscation mechanics):
- `OBFUSCATION_INVISIBLE` (3) - zero-width, bidi/RTL, confusables, odd codepoints.
- `OBFUSCATION_SPLIT` (2) - separator-split words, spaced single letters.
- `OBFUSCATION_LEET` (2) - high leet density in a token.

**PII-relevant class** (the signals that actually matter):
- `NEAR_PHONE` (3) - a 7-9 digit run; 10+ digits failing the mobile pattern; a
  leet/tally/Morse decode that does not validate as a mobile.
- `PARTIAL_SPELLED_DIGITS` (3) - 3+ spelled-digit tokens (any language, incl.
  collision words when clustered) not completing a validated phone.
- `DIGIT_DENSITY` (2) - unusually many digits in one message or across a conversation
  with no valid phone.
- `BRAND_MENTION` (2) - a platform/PSP brand or abbreviation word.
- `HANDLE_SOLICIT_SOFT` (3) - platform + letters-only common-word value, or a bare
  handle-shaped token.
- `SELFNAME_SOFT` (4) - the sender's OWN name in a sub-hard-threshold form.
- `REVERSAL_HINT` (2) - a token that reverses to a name/brand/word, or the words
  "backwards"/"reverse"/"ulta" near content.
- `CONTACT_INTENT_SOFT` (2) - an ask/steer phrase with no platform and no number.
- `ENTROPY_TOKEN` (2) - a high-entropy alphanumeric token (possible handle/cipher).
- `SEMANTIC_NUMBER_HINT` (1) - arithmetic/riddle/phoneword phrasing near "number".

**Behavioral / cross-message class** (brand-new capability; backend accumulation):
- `DIGIT_DRIP_CADENCE` (3) - several single-digit/number-word messages in a window.
- `SINGLE_CHAR_BURST` (2) - many one-letter messages.
- `CROSS_MESSAGE_ASSEMBLY` (4) - a near-phone or near-name assembling across messages
  below Veil's hard threshold.
- `BLOCKED_LEAK` (5) - a message Veil hard-blocked, recorded as a suspicion event
  (requires the wiring change in 3.3). Strongest single signal; near-zero FP because
  Veil was already certain.
- `BLOCKED_RETRY` (4) - a soft-signal message sent right after a Veil block.
- `EDIT_AFTER_SEND` (2) - a message edited immediately after sending (if edits exist).

### 3.2 Scoring: accumulate for admin review only (NO blocking)

- Per-message score = sum of fired signal weights (as today), now with class caps.
- **Ambient-class signals are excluded from the review-priority score** (they still
  record for context, but they do not rank a user up the offenders queue). This is
  the single most important false-positive firewall: a legitimate user who writes
  romanized Hindi all day never climbs the queue on that alone.
- **Diversity-weighting:** the offenders ranking favors users with MULTIPLE DISTINCT
  PII-relevant or behavioral signal types, not raw volume of one kind. One quirky
  legit pattern does not rank a user high.
- **Decay (currently absent):** give `UserSuspicionProfile.score` a time half-life
  (start ~14 days) so the queue reflects current risk, not lifetime noise.
- **Tiers are REVIEW LABELS only** (WATCH / ELEVATED / HIGH), used to sort and filter
  the admin queue. They do NOT trigger any block, mask, notification, or account
  action. Crossing a tier just raises the row's priority for a human.

### 3.3 Wiring (all backend, all feeding admin-only accumulation)

1. **Feed Veil blocks into suspicion.** Today suspicion only runs on messages Veil
   allowed, so it never even sees the strongest signal. Record a `BLOCKED_LEAK`
   suspicion event whenever Veil hard-blocks. Enables `BLOCKED_RETRY` too.
2. **Give suspicion its own cross-message window** (mirror `VeilService._build_window`)
   so the behavioral signals and `CROSS_MESSAGE_ASSEMBLY` can fire.
3. **Pass Veil's verdict into the suspicion scan** so it does not recompute near-miss
   and knows what Veil already saw.
4. Keep it synchronous, fail-open, anonymous-phase (unchanged).

### 3.4 Admin surface (the ONLY place suspicion has any effect)

Extend the existing admin API (feed / offenders / user-detail / review):
- Show tier, decayed score, and per-class breakdown in the offenders list.
- Add a `reset-suspicion-score` endpoint (like the existing `reset-strikes`) so an
  admin can clear a false accumulation in one click.
- Review actions keep their meaning (UNREVIEWED / REVIEWED / CLEARED / ACTIONED); any
  account action (suspend / ban / escalate) stays on the SEPARATE user-management
  endpoints a human triggers deliberately. Suspicion itself never acts.
- **Labeled-corpus feedback loop:** CLEARED events become BENIGN corpus candidates,
  CONFIRMED (ACTIONED) events become MALICIOUS candidates. A recurring confirmed
  near-miss surfaces a one-click prompt to promote it into a Veil hard rule (with the
  human adding corpus rows + rule; never auto-mutated). This is how the suspicion
  backlog actually improves Veil over time.

## 4. Branching each case into its false-positive-risky variants (the core)

For each PII family: the Veil HARD rule (certain, auto-block), then the branched
variants that leak PII but would cause false positives if hard-blocked, each with the
reason it would FP and the suspicion signal it feeds. These are the "all the ways a
person could do it that are good for the suspicion engine to hold."

### 4.1 Phone number

**Veil HARD:** a full, validated 10-digit Indian mobile (`[6-9]\d{9}`) reassembled
from any encoding - literal, spaced, dashed, spelled (English + Indic), leet-to-digit,
Morse, tally/run-length, hex/oct/bin, reversed, or combined across the window.

**Suspicion (FP-risky variants):**
- 7-to-9 digit run -> `NEAR_PHONE`. Why FP: OTPs, order ids, roll numbers, prices,
  PINs, room numbers are all 4-9 digits.
- 10+ digits that fail the mobile pattern (start 0-5, or 11-12 digits) -> `NEAR_PHONE`.
  Why FP: Aadhaar fragments, bank account numbers, transaction ids are not mobiles.
- 3-6 spelled number-words not completing a phone ("meet at nine, room four") ->
  `PARTIAL_SPELLED_DIGITS`. Why FP: times, counts, room numbers.
- Number words that collide with English/Indic ("two", "do", "to", "be", "for") used
  in prose -> only `PARTIAL_SPELLED_DIGITS` when clustered with other digit tokens.
  Why FP: "I have two things to do" is ordinary speech.
- Leet-to-digit that yields only 7-9 digits or needs aggressive folding -> `NEAR_PHONE`.
  Why FP: ordinary words leet-fold into digit-ish noise.
- Tally/run-length/emoji-count that does NOT validate as a phone ("soooo", "wait....",
  "-----", "⭐⭐⭐⭐⭐") -> `DIGIT_DENSITY` / structural only, heavily capped. Why FP:
  this is the benign noise budget; must never rank a user.
- Digits as years/scores/prices that nearly concatenate to 10 ("I scored 98, then
  76...") -> `DIGIT_DENSITY`. Why FP: legitimately number-heavy chat.
- A single digit or single number-word per message across several messages ->
  `DIGIT_DRIP_CADENCE` + `CROSS_MESSAGE_ASSEMBLY`. Why FP: countdowns, polls, reacting
  "1", "2", "3".
- Arithmetic / riddle digits ("half of eight, then the square root of eighty-one") ->
  `SEMANTIC_NUMBER_HINT` (very low). Why FP: unbounded, mostly innocent.
- Roman numerals in a run ("I, II, III") -> `SEMANTIC_NUMBER_HINT`. Why FP: lists.
- Phonewords ("my number spells PIZZA") -> `SEMANTIC_NUMBER_HINT`. Why FP: normal
  words map to dialpad digits.

### 4.2 Self-name

**Veil HARD:** the sender's own name token, length >= 6, as standalone / glued-in-
letters / separator-split / stretched / leet / reversed / collapsed across messages.

**Suspicion (FP-risky variants):**
- Short name (< 6 chars) glued inside letters ("heyyashhere", "iamomhere") ->
  `SELFNAME_SOFT` (low). Why FP: short name tokens (ash, om, raj, ria) are substrings
  of countless normal words.
- Reversed SHORT name (4-5 chars) -> `SELFNAME_SOFT` + `REVERSAL_HINT` (low). Why FP:
  short reversed strings collide with ordinary tokens.
- Disemvoweled name ("hrdk", "hmnsh") -> `SELFNAME_SOFT`. Why FP: consonant skeletons
  collide (hdfc, etc.).
- Name prefix only ("I'm Har...", "call me Him") -> `SELFNAME_SOFT`. Why FP: "hard",
  "harmony", "him" are words.
- Name as initials ("H A R D I K", "my initials are H J") -> `SINGLE_CHAR_BURST` +
  `SELFNAME_SOFT` when the letters spell the name. Why FP: initials are extremely
  common and benign.
- Name split across messages below the glue floor (two 3-char halves) ->
  `CROSS_MESSAGE_ASSEMBLY` (name). Why FP: the halves are ordinary fragments.
- Name phonetically ("sounds like car-thick") -> `SELFNAME_SOFT` (low). Why FP:
  describing a sound, not stating the name.
- Nickname / short form not present in `full_name` -> cannot be detected from content;
  route to human review only (note, not a signal).
- Partner's identity (guessing/revealing the OTHER person) -> deliberately NOT checked
  by Veil (anti-de-anonymization) and not content-detectable; handled via user reports
  / human review, out of scope for both scanners.

### 4.3 Social handle, email, UPI, platform

**Veil HARD:** explicit `@handle`; platform word + value containing a digit/`_`/`.`;
plain or verbose email; UPI `handle@psp`; URL; platform word near an explicit ask
within the proximity window; a known abbreviation paired with an explicit ask.

**Suspicion (FP-risky variants):**
- Platform word + letters-only COMMON-word value ("my insta is cool", "snap is fun")
  -> `HANDLE_SOLICIT_SOFT`. Why FP: the value is a real English word; may be
  commentary, not a handle.
- Bare platform / brand mention ("I love instagram", "paytm is down") -> `BRAND_MENTION`
  (low). Why FP: talking about an app is not sharing a handle.
- Platform ABBREVIATION alone ("ig", "wa", "tg", "dm", "fb") -> `BRAND_MENTION` only,
  capped. Why FP: "ig" = "I guess", "wa" = "wait", "dm" = "doesn't matter".
- Platform SLANG / codename ("the gram", "ghost app", "bird app", "big G") ->
  `BRAND_MENTION`. Why FP: oblique; could mean anything.
- Ask/steer with no platform and no number ("find me", "add me", "text me", "hit me
  up", "search my name", "same username everywhere") -> `CONTACT_INTENT_SOFT`. Why FP:
  all are ordinary idioms.
- Email with spaced letters / synonyms ("g m a i l dot com", "gee mail", "my id on
  google") -> `OBFUSCATION_SPLIT` + `BRAND_MENTION`. Why FP: spacing is emphasis; a
  "google" mention is benign.
- Email local-part look without a domain ("i'm rahul123") -> `HANDLE_SOLICIT_SOFT` /
  `ENTROPY_TOKEN`. Why FP: that is just a name plus a number.
- UPI PSP word with no handle ("paytm", "oksbi") -> `BRAND_MENTION`. Why FP: naming a
  payment app is not sharing a VPA.
- Bare domain-ish token without a known TLD ("meet.me", "cu.soon") -> structural only.
  Why FP: dotted sentence fragments.
- Handle-shaped token NOT after a platform word ("rahul_97 here", "its_me.123") ->
  `HANDLE_SOLICIT_SOFT`. Why FP: gamer-tag-style tokens appear in normal chat.
- High-entropy token (possible base64 / cipher / handle) -> `ENTROPY_TOKEN`. Why FP:
  keysmashes and typos look high-entropy too.

### 4.4 Structural / unicode / obfuscation

**Veil HARD:** strip invisible/bidi/confusable characters, THEN block only if an
underlying leak fires. Non-Latin letters block as NON_LATIN (English-only, no strike).

**Suspicion (FP-risky variants) - obfuscation WITHOUT a confirmed leak riding along:**
- Zero-width / bidi present but the visible text is benign -> `OBFUSCATION_INVISIBLE`.
  Why FP: copy-paste artifacts; emoji ZWJ sequences (family/profession emoji use ZWJ).
- Heavy leet on a non-PII word ("l33t h4x0r g4m3r") -> `OBFUSCATION_LEET`. Why FP:
  gamer speak.
- Many separators / spaced letters spelling a benign word ("s.o.o.o g.o.o.d",
  "l o v e", "f-i-n-a-l-l-y") -> `OBFUSCATION_SPLIT` / `SINGLE_CHAR_BURST`. Why FP:
  emphasis; the benign noise budget.
- A single confusable/homoglyph in a benign word (one Cyrillic "o") ->
  `OBFUSCATION_INVISIBLE`. Why FP: keyboard-layout artifact.
- Romanized Hindi/Tamil/etc. -> `ROMANIZED_INDIC` (ambient, capped). Why FP: it is how
  the whole user base talks.
- Keysmash / gibberish ("asdfghjkl") -> `GIBBERISH` (ambient, capped). Why FP:
  frustration, testing.

### 4.5 Behavioral (inherently ambiguous; ideal for suspicion, never for Veil)

These cannot be hard-blocked on a single message at all; they only mean something as
an accumulated backend pattern, which is exactly what the suspicion engine is for.
- Digit-per-message drip -> `DIGIT_DRIP_CADENCE`. Why not Veil: one digit is innocent.
- Single-char burst -> `SINGLE_CHAR_BURST`. Why not Veil: one letter is innocent.
- Cross-message near-phone/near-name assembly -> `CROSS_MESSAGE_ASSEMBLY`.
- Rephrase right after a Veil block -> `BLOCKED_RETRY`.
- Immediate edit after send -> `EDIT_AFTER_SEND`.
- Volume of soft signals over a session -> accumulation (the core of the engine).

## 5. False-positive governance

1. Veil blocks only validator-certain cases; anything that cannot be made zero-FP
   goes to suspicion, never to Veil.
2. Suspicion never blocks, masks, notifies, or auto-acts. It is backend-only and
   admin-only; the user sees nothing unless an admin acts manually.
3. Ambient signals are visibility-only and excluded from the review-priority score, so
   normal romanized-Hindi / emoji / gibberish chat never ranks a user.
4. Offender ranking is diversity-weighted and decayed, so one quirky legit pattern or
   stale noise does not surface a legitimate user.
5. Admin can reset a score instantly; CLEARED events feed the BENIGN corpus.
6. Every Veil hard rule adds BENIGN + MALICIOUS rows to `test_corpus.py` (stays
   green). Every suspicion signal adds rows to the suspicion "noise budget" corpus,
   which must stay at tier CLEAN for all benign inputs (keep the existing 10-line
   budget at zero, grow it with romanized-Hindi paragraphs, number-heavy innocent
   chat, emoji/divider spam).
7. Bump `RULESET_VERSION` and `SUSPICION_RULE_VERSION` on any data change.

## 6. Rollout

- **Phase 0 - Veil safety + audit:** gate every text surface, strip all
  invisible/bidi/confusable chars, apply the MEETING precision FP fix, reversed-digit
  phone.
- **Phase 1 - Veil high-value hard blocks:** reversed name, name split across
  messages, spelled-digit drip reassembly, leet-to-digit phone, contextual romanized
  digits, letters-only handle (shadow first), paired platform abbreviation.
- **Phase 2 - Suspicion foundation:** classed taxonomy (3.1), single source of truth
  for weights, feed Veil blocks + verdict in, suspicion's own window, decay + review
  tiers + ambient caps + diversity ranking (3.2), score-reset endpoint, config keys +
  validators. Record-only (it always was).
- **Phase 3 - Suspicion breadth:** implement the full section-4 variant signals,
  grow the suspicion noise-budget corpus, build the admin per-class breakdown and the
  labeled-corpus feedback loop.
- **Phase 4 - Polish:** behavioral signals (EDIT_AFTER_SEND etc.), gibberish Markov
  upgrade, remaining Veil P2/P3 hacks.

## 7. Open decisions for the owner

1. **Decay half-life** (start 14 days) and review-tier thresholds (WATCH / ELEVATED /
   HIGH) - confirm or set. These only sort the admin queue; they never block.
2. **`BLOCKED_LEAK` feed-in.** Confirm we should record a suspicion event when Veil
   hard-blocks (recommended: it is the strongest signal and is near-zero-FP). Purely
   backend accumulation; no user effect.
3. **raw_message retention.** Stored "temporarily", scrubbed only on erase. Set an
   auto-scrub window (e.g. N days) now that the feed will carry more rows.
4. **Media policy (Veil hack 27).** Restrict image/file/voice in the anon phase
   (simple, recommended) vs OCR + QR decode (heavier). Product + FE call.
5. **Gibberish Markov model** (planned, not shipped) - build now in Phase 4 or defer.

## 8. Test plan

- Veil: extend `test_corpus.py` per hard rule (BENIGN + MALICIOUS), keep green.
- Suspicion guard: one assertion per new signal, and GROW the benign noise-budget
  corpus (romanized Hindi, number-heavy innocent chat, emoji/divider spam, short-name-
  in-word, gamer leet) that must all stay tier CLEAN / score 0 on the ranking scale.
- Suspicion service: decay math, ambient-class exclusion from ranking, diversity
  ranking, tier labels, score reset, CLEARED-reopen.
- Integration: the missing `send_text` -> suspicion path test, plus Veil-block ->
  `BLOCKED_LEAK` event. Assert suspicion still returns None / never blocks.
