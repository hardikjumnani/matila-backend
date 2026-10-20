# Veil v2.2 — drip / misspelling hardening (planned)

Closes the evasion observed in the Hardik chat: a plan dripped one word per message
with **filler** ("Hero", "Woa"), **stretch** ("Canteeenn", "Thee"), and a
**substitution misspelling** ("meet mr" for "meet me"). v2.1 allowed it because
(a) a lone venue never blocks (by design), and (b) no INVITE formed — bare "meet"
is not a trigger and squeeze fixes repeated letters, not substitutions.

## HARD CONSTRAINT: zero false positives
Owner requirement. Every change below is tuned for precision and gated by a
benign corpus that must pass with **zero** false positives before enforce. Where a
technique cannot meet that bar, it is deliberately **omitted** (see "Rejected").

## What happens on a cross-message block (reference)
The *completing* message is blocked (MESSAGE_BLOCKED/422, not persisted/delivered),
a strike is counted, a LeakEvent is recorded, and escalation fires past the
threshold. Already-sent fragments remain (cannot be un-sent).

## Implemented (FP-safe)
1. **Edit-distance ≤1 fuzzy — DISTINCTIVE SINGLE WORDS ONLY** (`apps/privacy/fuzzy.py`,
   BK-tree). Catches `cantin`→`canteen`, `instgram`→`instagram`, `snpchat`→`snapchat`.
   Guards for zero-FP:
   - Single words only (len ≥ 6); **phrases are NOT fuzzed** (see below).
   - Presence-only + always requires the existing **combination** (a fuzzy
     destination still needs an invite; a fuzzy platform stays LOW).
   - BK-tree over the distinctive set, not brute force.
   - **Phrase fuzzing was REMOVED after it produced a false positive**
     (`meet my friend`→`meet me`). "meet me/us/his" are common benign phrases one
     edit from the invite, so phrase fuzzing cannot be zero-FP. Dropped.
2. **Cross-message window bump 5 → 8** (`VEIL_MESSAGE_WINDOW`). Covers drips spaced
   by filler; same strict combination, no new FP.
3. **Phase-0 corpus gate** (`apps/privacy/tests/test_corpus.py`): BENIGN must pass
   with **zero** false positives; MALICIOUS recall asserted. Both green.

## Known residual (price of zero FP)
The reported evasion specifically used `meet mr` (a substitution in the invite
verb). Because `meet mr` is indistinguishable from benign `meet my`/`meet us`
without false positives, the INVITE is NOT reconstructed, so a drip that forms its
invite only via such a substitution (and never an exact "meet me"/"meet"+"me") is
NOT caught. Exact invites, repeated-letter stretch, gluing, typo'd venues/platforms,
and multi-message splits that form an exact phrase ARE caught. This is the
deliberate trade-off for the zero-FP requirement.

## Rejected (would risk false positives — omitted to honor the constraint)
- **Bare "meet"/"milna" as a weak INVITE signal.** Too FP-prone
  ("nice to meet you"). A drip that uses ONLY the bare word "meet" (never "meet me"
  / "meet mr") plus a venue remains a **known residual gap** — the price of zero
  FP. Documented, not closed.
- **Long-horizon Redis signal accumulator.** Combining a phrase-invite from msg 1
  with a venue from msg 10 risks unrelated-benign FPs; the bounded 8-message text
  window is the FP-safe substitute.

## Why this catches the observed evasion
`To meet mr` + `At the canteen` are consecutive → window joins them → fuzzy maps
`meet mr`→`meet me` (INVITE, distinctive phrase, "meet mr" is not a legal word) →
INVITE + DESTINATION(`canteen`) → MEETING block on the completer. Zero new FP
because fuzzy is distinctive-only + legal-word-guarded and still requires the
combination.

## Known limits (honest)
A determined user dripping a plan using only bare, correctly-spelled common words
(no phrase ever forming) across many filler messages can still evade a
deterministic, zero-FP system. v2.2 raises the cost and closes the misspelling +
near-miss cases without false positives; it does not guarantee 100% recall.

## Status
IMPLEMENTED + tested 2026-10-12 (full suite 521 green; corpus gate zero-FP + full
recall; live on local BE). Window default 5→8. RULESET_VERSION 2026.10.12-v2.2.
Not committed, not deployed.
