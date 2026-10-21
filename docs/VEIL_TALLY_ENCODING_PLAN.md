# Veil — Tally / Run-Length Digit-Encoding Evasion — Plan

## The evasion
A user encodes a phone number as counts of a repeated symbol: **N dots = digit N**,
groups space-separated. Example: `.......  .....  .  ......` -> `7 5 1 6`, and a
10-group sequence spells a full number. No literal digits appear, so the current
Number Reassembler finds nothing and the phone rule never fires. Works with any
repeated symbol (dots, dashes, bars, asterisks, ...) and, as harder variants, with
repeated letters or emoji.

## Why it slips through today
`leakguard.extract_digits(raw)` = `normalize.prefold_numeric` + tokenize + keep
`isdigit()` chars -> `looks_like_phone` (`[6-9]\d{9}`) + libphonenumber (only at
>=7 digits, `_PHONE_MIN_DIGITS`). Tally text yields **0 digits**, so there is
nothing to match.

## Fix: a tally-decode pass that feeds the EXISTING phone validator
Add `decode_tally(text) -> str` (new, deterministic) that:
1. Scans for a **contiguous sequence of same-symbol runs** separated only by
   whitespace / simple delimiters (no letters or digits interleaved in the run).
2. A run = >=1 repetitions of ONE symbol from a `TALLY_CHARSET`
   (`. · • * - _ | / ~ + =` ..., extensible). Different runs may use different symbols.
3. Each run length -> a digit: `digit = len % 10` (10 -> 0; 1-9 -> themselves).
   Ignore runs longer than `MAX_RUN` (e.g. 12) — not a digit tally.
4. Only a sequence of **>= `MIN_GROUPS`** consecutive runs counts (start at 7;
   Indian mobile is 10). Shorter stretches are discarded.
5. Concatenate the decoded digits -> candidate digit string.

Then run the candidate through the **same** `looks_like_phone` + libphonenumber
(region IN) gate used for real digits, and fold it into the cross-message digit
window (so a tally number split across messages is still caught). **Block only if
it validates as a phone number.**

## Zero-FP design (non-negotiable)
Must never block a normal message. Guards:
- **High group count** (`MIN_GROUPS >= 7`): ordinary text almost never has 7+
  consecutive space-separated pure-symbol runs. `...`, `wait......`,
  `ok. yes. no.`, several `...` in a sentence -> too few groups and broken up by
  words, so they never reach the threshold.
- **Pure-symbol runs only** (phase 1): any letter/word between runs ends the
  sequence. `nooooo wayyyy` is excluded.
- **Bounded run length** (`MAX_RUN`): a 40-dot divider is ignored.
- **Must pass the real phone validator**: random dot-counts that don't form a valid
  number don't block. A false positive would need 7+ consecutive pure-symbol runs
  whose lengths *happen* to spell a valid phone — effectively impossible by accident.

## Config (app_config, runtime-tunable, like the other veil_* knobs)
`veil_tally_charset` (default symbol set), `veil_tally_min_groups` (7),
`veil_tally_max_run` (12). Tunable without a deploy.

## Integration points
- `apps/privacy/normalize.py`: add `decode_tally`.
- `apps/privacy/services/leakguard.py`: compute `tally_digits = decode_tally(raw)`,
  run it through `looks_like_phone` + libphonenumber, add to the combined
  cross-message digit string, emit a PHONE/number verdict on a hit. Keep it in the
  **digit path only** (never the keyword path).
- Latency: one extra linear pass + a conditional validator call only when a long
  tally sequence exists; sub-ms common case (no tally -> early out).

## Tests (corpus-gated, both sides) — `apps/privacy/tests/test_corpus.py`
- **Malicious (block):** dot-tally full number; dash-tally; mixed-symbol tally;
  tally split across two messages (window).
- **Benign (do NOT block):** `...`, `wait......`, `ok. yes. no.`,
  `really?? ... hmm...`, a decorative divider `----------`, bullets `• • •`.

---

# Phase 2 — harder encodings (letters, emoji, separators, Morse)

## Architecture: a candidate-digit extractor pipeline (single FP gate)
Refactor the numeric path into a pipeline of **extractors**, each yielding a
candidate digit string; EVERY candidate goes through the SAME gate —
`looks_like_phone` + libphonenumber(region IN) + the cross-message digit window —
and a message blocks only if ANY candidate validates as a real phone number. FP
control lives in exactly one place (the validator), so adding decoders never
relaxes safety. This is the key to keeping zero-FP while the decoders multiply.

Extractors:
1. Literal digits (existing).
2. Spelled digits — "seven five one" (existing dictionaries).
3. Symbol run-length tally (Phase 1).
4. Letter run-length tally (Phase 2).
5. Emoji / grapheme run-length tally (Phase 2).
6. Separator / space-count tally (Phase 2).
7. Morse-encoded digits (Phase 2).

The decisive, shared guard for all of them: **the decoded digits must validate as a
phone number.** Random expressive repetition essentially never produces a valid
10-digit Indian mobile starting with 6-9, so even the letter/emoji decoders stay
near-zero-FP behind this gate.

## 2a. Letter-repeat tally
`ooooooo ooooo o oooooo` -> 7,5,1,6. Generalize `decode_tally` to runs of a single
LETTER. Letters appear in prose, so add guards on top of the shared validator:
- **Standalone-span guard:** the run-sequence must be a standalone block — the
  matched span is only single-letter runs + whitespace/punctuation, not embedded in
  a sentence with real words. (`sooo good` is embedded prose and is a single run
  anyway; an attack is "just the code".)
- **Stricter group floor:** `MIN_GROUPS_LETTERS` default = full phone length (10),
  stricter than symbols' 7; tune via corpus.
- Validator gate (decisive).
- Corpus FP cases to pass: `nooooo`, `yessss`, `lmaooooo`, `sooo good vibes`,
  `haha haha haha`, `a b c d e`, `ok ok ok ok`.

## 2b. Emoji / grapheme tally
`👍×7 👍×5 ...` -> 7,5. `decode_tally` generalized to grapheme clusters (one
repeated emoji per run). Same standalone-span + validator gate. FP cases to pass:
`🔥🔥🔥`, `😂😂😂😂😂`, mixed reaction spam — all either one group or don't validate.

## 2c. Separator / space-count tally
Digits as the NUMBER OF SPACES (or a separator char) between tokens:
`hi&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;there&nbsp;&nbsp;&nbsp;&nbsp;you` ->
7,4. Decoder measures consecutive whitespace/separator run lengths; a sequence of
>= MIN_GROUPS multi-space gaps -> candidate digits -> validator. Ignore the normal
single-space case entirely so it never engages on ordinary text. Lower-confidence,
so keep it validator-gated and shadow-first.

## 2d. Morse-encoded digits
Distinct decoder (pattern-based, NOT run-length): Morse digit patterns
(`0=-----, 1=.----, ... 9=----.`), symbols separated by spaces, digits by `/` or a
double space. Detect a span that is purely 5-symbol dot/dash groups; decode to
digits; validator gate. Zero-FP by distinctiveness — a 10-digit Morse string is long
and unmistakable, and normal text is not Morse. (Note: Phase 1 run-length tally and
Morse both use dots/dashes but decode differently; run the Morse decoder only when
each group is a 5-symbol dot/dash pattern.)

## Considered but DEFERRED (too FP-risky for a zero-FP engine)
- **Word-length tally** (digit = length of each word): normal sentences ARE
  sequences of word-lengths; even behind the validator a 10-word phrase could
  accidentally form a valid mobile and block a normal sentence. Violates zero-FP;
  defer. If ever abused, gate on the message being only short words + validator, and
  ship in shadow mode first.
- **Arbitrary ciphers** (ROT/base64 of the number, etc.): open-ended; out of scope
  for a deterministic engine. Rely on human review + ESCALATE for repeat offenders.

## Rollout (Phase 2)
Ship each extractor behind its own config flag
(`veil_tally_letters_enabled`, `veil_emoji_tally_enabled`,
`veil_separator_tally_enabled`, `veil_morse_enabled`). Default the riskier ones
(letters, separator) to **shadow first** (record, don't block) to confirm zero-FP on
real traffic, then flip to enforce; symbol tally (Phase 1) and Morse are safe enough
to enforce immediately. Expand the corpus gate heavily per extractor.

## Perf
Each extractor is a linear pass with an early-out (no long run / no Morse chars /
single spaces only -> skip). The common message touches none; net stays sub-ms.

## Residual
`len % 10` maps 10 -> 0, so a 0 digit is expressible as a 10-run (covered). Any tally
sequence shorter than its MIN_GROUPS is intentionally ignored (zero-FP wins over
catching a partial number). Non-digit targets (email/UPI/handles) are poorly suited
to tally-encoding and remain covered by their own rules.
