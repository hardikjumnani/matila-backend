# Veil hardening - top 30 evasion hacks to solve

> Status: PLAN ONLY (2026-10-25). No code changed. Builds on the shipped Veil
> engine (v2.2, `RULESET_VERSION 2026.10.12-v2.2`). Companion to
> `VEIL_ENGINE_PLAN.md`, `VEIL_V2*_PLAN.md`, `VEIL_SELFNAME_GLUE_PLAN.md`,
> `VEIL_TALLY_ENCODING_PLAN.md`, `VEIL_MEETING_PRECISION_PLAN.md`,
> `VEIL_ENGLISH_ONLY_PLAN.md`.

## Prime directive (unchanged)

Veil must block every PII-reveal attempt during the anonymous phase WITHOUT ever
hindering a legitimate user. Zero false positives wins every conflict. Every new
detector in this plan ships only with new BENIGN and MALICIOUS rows added to
`apps/privacy/tests/test_corpus.py`, and the whole corpus stays green. A hack we
cannot solve inside the zero-FP floor is marked WON'T-FIX with the reason, not
forced in.

## What is already solved (do NOT re-build these)

From the engine map, these evasions are already covered and must stay covered:

- Plain / spaced / dashed / +91 / 0-prefixed / country-code phone; digits
  scattered in prose; digits split across messages WITHIN the 8-message window
  (digit reassembler + `combined_digits`).
- Spelled-out number words in English + 10 Indian languages ("nine four four"),
  "double"/"triple" multipliers.
- Morse phone, symbol/letter run-length tally (dots, dashes, repeated emoji),
  hex/octal/binary/Devanagari digits.
- Verbose email ("foo at gmail dot com", "(at)", "at the rate", "(dot)"), plain
  email, UPI PSP handles, URLs incl. `linktr.ee/x`, explicit `@handle`,
  "platform word + value with a digit/`_`/`.`".
- Self-name: standalone, glued-in-letters, separator-split, stretch, basic leet
  (0,1,3,4,5,7,@,$), cross-script confusables (Cyrillic/Greek), NFKC fullwidth.
- Zero-width stripping (ZWSP/ZWNJ/ZWJ/word-joiner/BOM/soft-hyphen), accent
  folding, particle degluing, letter-squeeze.
- English-only: any non-Latin LETTER blocks as NON_LATIN (romanized Hindi/Tamil
  still passes, by design).
- Cross-message keyword/meeting completion within the window ("add me" then "on
  insta"), blocked attempts never persisted (no window poisoning).

Central files: detectors + thresholds in `apps/privacy/services/leakguard.py`;
normalization in `apps/privacy/normalize.py`; data in `ruleset.py` /
`languages.py`; orchestration + window in
`apps/privacy/services/veil_service.py`; zero-FP gate `test_corpus.py`.

---

## The 30 hacks (ranked within families; P1 highest)

Legend: GAP = not detected at all; PARTIAL = detected only in some forms.
Priority P1 = high value and FP-safe and realistic, do first; P2 = worth doing;
P3 = low value or high FP cost or semantic, several are WON'T-FIX.

### Family A - Number / phone encoding

**1. Spelled digits dripped one token per message (the "O N E" hack). [GAP, P1]**
Owner-observed. Sender sends `O`, then `N`, then `E` as separate messages (or
`nine`, `four`, `four` one per message) so the rolling window never sees the whole
word. Current cross-message path reassembles DIGITS but not spelled-digit words
scattered as single letters: `extract_digits` tokenizes `[a-z]+|\d+`, so joined
"o n e" is three tokens, none a spelled digit.
Defense: in the digit reassembler, after the normal pass, also attempt a
glued-letter pass over the windowed `collapse_all` view: concatenate the window's
letters and match the spelled-digit automaton against the continuous string
("onefourfour" -> 1,4,4), AND detect single-letter NATO/number-word fragments
across messages by accumulating leading letters. Gate the whole thing behind the
existing `_PHONE_RE` validator so nothing blocks unless a full 10-digit mobile
reassembles. FP risk: low, because the phone validator is the only gate; add
BENIGN rows for innocent single-letter chatter ("o", "k", "lol", acrostic-free
short messages).

**2. Slow drip beyond the 8-message window. [GAP, P2]**
Sender pads with filler so each real digit lands >8 sent-messages apart, falling
out of `veil_message_window` (8) / `MAX_WINDOW_CHARS` (240) / `MAX_ACCUMULATED_DIGITS` (32).
Defense: keep a compact per-chat "digit accumulator" for the sender that survives
beyond the raw message window (store only extracted candidate digits + a decay,
not text), so a number assembled over 20 messages still trips `_PHONE_RE`. Cap
length, decay on reveal / long idle. FP risk: moderate (benign numbers like
scores, years, prices accumulate). Mitigate with the phone validator gate
(`[6-9]\d{9}`), a sliding cap, and reset on any non-digit-dense stretch. Add
BENIGN rows for people who legitimately mention many numbers.

**3. Letter / leet encoded digits in the phone path. [GAP, P1]**
`o`=0, `l`/`i`=1, `z`=2, `e`=3, `a`=4, `s`=5, `b`=6/8, `t`=7, `g`/`q`=9. e.g.
"nO sl2 ..." or "my no is nine 4 fOur". Today the leet map is applied only to the
keyword/name views, never to the digit path, so letter-encoded digits do not
reassemble.
Defense: add a SECOND, conservative digit extraction pass that leet-folds letters
to digits (o->0, i/l->1, e->3, a->4, s->5, t->7, b->8, g->9), gated ONLY by the
full `_PHONE_RE` 10-digit mobile match. Do NOT fold ambiguous ones that wreck
prose (keep `b`=8 only, not 6, to reduce noise), and only accept the folded
string if it validates as a phone. FP risk: contained by the validator; a normal
sentence almost never leet-folds into a valid 10-digit `[6-9]` number. Add BENIGN
prose rows.

**4. Romanized Hindi / regional number words that collide with English + spelling
variants. [PARTIAL, P1]**
`do`=2, Gujarati `be`=2, `to`/`oh` are deliberately excluded from the spelled map
(English collisions), and variant spellings (chhah/cheh/chhe=6, char/chaar=4,
teen/tin=3, paanch/panch=5, sat/saat=7, aath/ath=8, nau/no=9, shunya/sifar=0) are
incomplete. So a number spelled Hinglish with a 2 ("nau do teen ...") does not
fully reassemble.
Defense: add the collision-prone tokens (`do`, `be`, etc.) ONLY inside the digit
reassembler and ONLY when flanked by other confirmed digit tokens (contextual:
"nau DO teen" -> accept `do`=2 because neighbours are digits), never standalone.
Expand variant spellings in `languages.py spelled_digits`. Gate by `_PHONE_RE`.
FP risk: low with the "neighboured by digits" rule; add BENIGN rows ("i have to
go", "do you", "be there").

**5. NATO / aviation phonetics and phonetic-alphabet digits. [GAP, P2]**
"niner", "fower", "tree"=3, or letters via "alpha bravo charlie" to spell a handle.
Defense: add NATO digit words (niner, fower, tree) to `spelled_digits` (gated by
`_PHONE_RE`), and add the NATO letter set as a glued-letter decoder for handles /
self-name (alpha->a ...), gated by self-name validator or handle rules. FP risk:
low for the number words; moderate for the letter set (common names collide),
so keep the letter decoder behind self-name / handle validation only. Add BENIGN
rows.

**6. Stylized unicode digits that survive NFKC + digit-confusable fold. [PARTIAL, P3]**
NFKC already folds fullwidth and most math/superscript/circled digits, and keycap
emoji keep their ASCII base digit. Residual: negative-circled (❶), segmented-LCD
(🯱), tag digits (U+E0030+), some dingbats.
Defense: add a small digit-confusable table in `prefold_numeric` mapping the
residual code points to ASCII digits. FP risk: none (pure additive mapping to the
digit view). Low value (rare in practice), hence P3.

**7. Keypad phonewords. [GAP, P3 / likely WON'T-FIX]**
"my number spells PIZZA" / "CALL-4-ME" (letters map to dialpad digits).
Why hard: requires mapping arbitrary words to dialpad digits, which collides with
all normal text. Defense (if ever): only fire when a token is explicitly framed as
a number ("number spells", "it spells") AND maps to a `_PHONE_RE`-valid 10 digits.
FP risk: high. Recommend WON'T-FIX unless seen in the wild.

**8. Roman numerals as digits. [GAP, P3 / likely WON'T-FIX]**
"IX IV IV ..." Why hard: I/V/X/C/D/M collide heavily with prose and names. FP risk:
high. WON'T-FIX unless observed; if needed, require a long pure-numeral run gated
by `_PHONE_RE`.

**9. Separator-count and space-count and emoji-count tally. [PARTIAL / DEFERRED, P2]**
Phase-2 tally from `VEIL_TALLY_ENCODING_PLAN.md`: count of separators ("...."=4) or
spaces or grouped emoji as digits. Symbol/letter run-length is done; the
count-based variants are deferred.
Defense: implement the deferred tally extractors behind a shadow sub-flag first,
measure FP on the corpus, then enforce. Gate by `_PHONE_RE`. FP risk: the whole
reason it was deferred (normal "wait....", dividers). Keep the existing BENIGN
tally rows green and add more.

**10. Arithmetic / riddle digits. [GAP, P3 / WON'T-FIX]**
"first is half of eight, then square root of eighty one ..." Pure semantics. FP and
cost both high. WON'T-FIX; the second-hand suspicion engine can flag the pattern
for human review instead of blocking.

### Family B - Self-name reveal

**11. Reversed name. [GAP, P1]**
Owner-observed. "kidrah" for Hardik, "iknmujnah" style reversal. No reversal logic
exists.
Defense: add a Tier-3 to `_self_name`: for name tokens length >= 5, also test
`collapse_all(tok)[::-1]` (and its leet fold) as a substring of `collapse_all(raw)`.
FP risk: very low (a 5+ char reversed name appearing by chance is rare); keep the
min length at 5 or 6 and self-name-only so a partner is never blocked. Add BENIGN
rows (common words that reverse into nothing) and MALICIOUS reversed-name rows.

**12. Name split across messages. [GAP, P1]**
"Har" then "dik". Names are not reassembled across messages (only digits are).
Defense: in the cross-message completer, run `_self_name` over the windowed
`collapse_all(prior_text + " " + raw)` with the sender's name in context, so
"har"+"dik" -> "hardik" trips Tier-2 (>= 6) / Tier-3 reversal. FP risk: low (same
glue logic already proven zero-FP in a single message). Add MALICIOUS split rows.

**13. Disemvoweled name. [GAP, P2]**
"Hrdk", "Hmnsh" (vowels dropped). Defense: add a vowel-drop view of the name token
and match it against a vowel-dropped `collapse_all(raw)`, only for tokens whose
consonant skeleton is >= 4 and distinctive. FP risk: moderate (consonant clusters
collide); keep min length high and self-name-only. Add BENIGN rows.

**14. Name as initials / acrostic. [GAP, P3 / mostly WON'T-FIX]**
"H.. A.. R.. D.. I.. K" or first letters of consecutive messages. Defense: only the
single-message dotted-initials form is tractable ("h a r d i k" already collapses
via Tier-2); the cross-message acrostic is covered by hack 12's completer. The
free-form acrostic (first letter of each sentence) is WON'T-FIX (unbounded FP).

**15. Extended leet / confusable in name. [PARTIAL, P2]**
Current leet map misses `l`->1/i, and 6/8/9 letter substitutions. "h8rdik"
(8->a? no), "hard1k" works, "hardlk" (l) does not.
Defense: extend `_LEET` with `l`->1 handling and a few more, applied to the
keyword/name views only. FP risk: low-moderate; validate against corpus. P2.

**16. Reversed phone digits. [GAP, P2]**
"read my number backwards: 0123456789". The reversed string only matches `_PHONE_RE`
if its first digit is 6-9, so many reversed numbers slip.
Defense: also test `_PHONE_RE.search(ctx.combined_digits[::-1])`. FP risk: tiny
(still needs 10 digits matching the mobile pattern). Cheap; bundle with hack 11.

### Family C - Social handle / contact

**17. Pure-letters social handle after a platform word. [GAP, P1]**
"my insta is coolguy", "snap: johnsmith" (no digit/`_`/`.`). Deliberately not
blocked today to avoid FP, but it is one of the most common real leaks.
Defense: allow a letters-only value after a platform word ONLY when the proximity
is tight (platform immediately followed by a connector then a single token) AND
the token is not a common English word (dictionary gate) AND length >= 4. FP risk:
the reason it was excluded; mitigate with the common-word blocklist + tight
proximity. Pilot in shadow mode, measure FP, then enforce. Add many BENIGN rows
("my insta is cool", "my insta is private", "is your insta active").

**18. Platform abbreviations / slang / codenames. [PARTIAL, P1]**
"ig", "wa", "w/a", "snap", "tg", "the gram", "ghost app", "the bird app", "big G".
Curated platform list + fuzzy (edit-distance 1) misses short abbreviations and
slang.
Defense: expand `ruleset.PLATFORM_WORDS` with vetted abbreviations/slang, but keep
very short ones (ig, wa, tg) gated so they only count toward SOLICITATION/STEERING
when paired with an ASK/STEER signal (never as a lone platform mention). FP risk:
"ig" = "I guess" collision, so pairing-only. Add BENIGN rows.

**19. Steering with no platform token. [GAP, P2]**
"search my name", "find me, same username everywhere", "you know where to find me".
No platform word -> solicitation/steering does not fire.
Defense: add a SEARCH/FIND-ME signal class; block when SEARCH + self-reference +
(name hint or handle hint) co-occur. FP risk: high for bare "find me"; require the
combination. P2.

**20. Spaced / synonym email and domain. [PARTIAL, P2]**
"g m a i l dot com", "gee mail", "my id on google". Defense: add a spaced-letter
collapse for known mail domains in the email verbose path and a few domain
synonyms. Gate tightly. FP risk: moderate; corpus-test.

**21. Verbose / spelled UPI. [PARTIAL, P2]**
"myname at oksbi", "number at paytm". Current UPI is regex `handle@psp`.
Defense: extend the verbose-email style decoder to UPI PSP handles ("at oksbi" ->
`@oksbi`). FP risk: low (PSP handles are distinctive). P2.

**22. @handle evading the lookbehind / embedded in words. [PARTIAL, P3]**
Leading separators or handle glued inside a word to dodge `(?<![a-z0-9._@])@`.
Defense: also scan the `collapse_all` view for `@token`. FP risk: low. P3.

### Family D - Structural / unicode / cross-cutting

**23. Expanded invisible / format-char stripping. [PARTIAL, P2]**
Beyond the current zero-width set: braille blank (U+2800), Hangul filler (U+3164),
combining grapheme joiner (U+034F), remaining variation selectors, other Cf
controls used as separators between digits/letters.
Defense: extend `_ZERO_WIDTH` / the strip step to all `Cf` format chars and the
known invisible letters, in all four normalization views. FP risk: none (these are
non-printing). Easy win, do early.

**24. Bidirectional / RTL override controls. [GAP, P3]**
U+202A..202E / U+2066..2069 used to visually reverse or hide text. Since Veil scans
logical order, the real content is already seen, but these chars can also split
tokens. Defense: strip all bidi controls in normalization (folds into hack 23).
FP risk: none. Low value, bundle with 23.

**25. Homoglyphs beyond Cyrillic/Greek + digit homoglyphs. [PARTIAL, P3]**
Armenian/Cherokee/other-script lookalikes are already caught by the NON_LATIN block
(strong backstop). Residual: Latin-named oddities and digit lookalikes.
Defense: grow `CONFUSABLES_TABLE` from the Unicode confusables data for the Latin
range; add digit confusables (covered by hack 6). FP risk: low. P3.

**26. Base64 / ROT13 / cipher-encoded number or handle. [GAP, P3 / WON'T-FIX]**
"OTQ0..." (base64 of digits). Why hard: decoding arbitrary encodings of arbitrary
text is unbounded and FP-heavy. Recommend WON'T-FIX; route to the suspicion engine
as a soft signal (high-entropy token) for human review, never an auto-block.

**27. Non-text channels (image / QR / screenshot / voice / sticker / profile pic).
[GAP, P1 - policy, not a text detector]**
A number photographed, a QR code, a handle in a voice note or profile photo.
Defense: this is a product/policy decision, not a leakguard regex. Options:
(a) disallow image/file/voice sends during the anonymous phase (simplest, safest);
(b) OCR + QR decode on anon-phase media before delivery (heavier). Recommend (a)
for launch. FP risk: n/a (policy). Raise with owner; coordinate with FE.

**28. Un-gated text surfaces (audit). [AUDIT, P1]**
Any user-authored text that reaches the partner in the anon phase but does NOT run
through `VeilService.inspect_text` is a free bypass: message edits, replies/quotes,
reactions with custom text, chat "topic"/nickname fields, report free-text echoed
back, link previews. Today only `message_service.send_text` is gated.
Defense: inventory every anon-phase text path and route each through Veil (or block
free-text there). FP risk: n/a. Do this first - a single ungated field defeats all
30 detectors.

**29. Sub-token window granularity. [GAP, P2]**
The cross-message completer joins WHOLE messages; a leak that only forms at a
boundary the whole-message join does not bridge can slip. Defense: when building
the window, also test the `collapse_all` concatenation of the window (letters and
digits) so boundaries vanish, not just space-joined text. Overlaps hacks 1 and 12.
FP risk: low; corpus-test.

**30. Phonetic / soundalike name or number. [GAP, P3 / WON'T-FIX]**
"sounds like car-thick", "my digits rhyme with ...". Pure semantics / phonetics.
FP and cost high. WON'T-FIX; suspicion-engine soft signal only.

---

## Companion fix (not a hack - a false positive that HURTS legit users)

`VEIL_MEETING_PRECISION_PLAN.md` documents that INVITE + TIME with no place still
blocks poetic/benign Hindi ("kal milte hain", "do dil milte hain shaam ko"). The
fix (drop INVITE+TIME from `_meeting_blocks`, leakguard.py:435) is NOT yet applied.
Because zero false positives wins over everything, apply this fix as part of this
work and add those benign lines to the corpus. This is the opposite of an evasion
but it is a live breach of the prime directive.

## Suggested rollout (phased, each phase keeps test_corpus green)

- **Phase 0 (safety + audit, do first, cheap):**
  28 (gate every text surface), 23 + 24 (strip all invisible/bidi chars),
  companion MEETING fix, 16 (reversed-digit phone one-liner).
- **Phase 1 (high value, FP-safe, realistic):**
  11 (reversed name), 12 (name split across messages), 1 (spelled-digit drip),
  3 (leet digits), 4 (collide/variant romanized digits), 17 (letters-only handle,
  shadow first), 18 (platform abbreviations, pairing-gated).
- **Phase 2 (worthwhile):**
  2 (beyond-window digit accumulator), 9 (count tally, shadow first), 13
  (disemvoweled name), 15 (extended leet), 19 (search/find-me steering), 20/21
  (spaced email + verbose UPI), 29 (sub-token window), 5 (NATO digits).
- **Phase 3 (low value / exotic):**
  6, 22, 25 (unicode/handle exotica).
- **WON'T-FIX (route to suspicion engine as soft signals, never auto-block):**
  7 (phonewords), 8 (roman numerals), 10 (arithmetic), 26 (cipher), 30 (phonetic).

## Zero-FP method for every item

1. Add BENIGN rows (the legit phrasing the detector could trip on) AND MALICIOUS
   rows (the evasion) to `test_corpus.py` BEFORE wiring the detector.
2. Keep every new numeric decoder gated by the single `_PHONE_RE` validator so a
   non-phone decode can never block.
3. Ship FP-risky detectors (17, 9, 2) in SHADOW mode first; read `LeakEvent` rows;
   only flip to enforce when benign hits are zero.
4. Keep self-name detectors sender-name-only so a partner is never blocked.
5. Bump `RULESET_VERSION` and re-export the FE ruleset mirror on any ruleset change.
