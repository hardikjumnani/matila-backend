# Veil hardening: self-name spelled letter-by-letter

Status: PLAN ONLY (no code yet). Owner-reported 2026-10-30.
Scope decision (owner): do **Fix A** and **Fix B** (both Veil-side, zero-FP).
Do NOT do the hard cross-message residual (see Section 6 - out of scope).

Source case: prod chat `5ee0d00a-0086-4fa8-9448-043f6414beb3`, sender
`Ujjwal Kumar Rai` (`ujjwal.25bcs10087@sst.scaler.com`), ANONYMOUS phase.

## 1. Evidence

Veil hard-blocked the direct forms (LeakEvents, never delivered):
- `I am Ujjwal` -> BLOCK self_name (Tier 1 boundary match)
- `My name is Ujjwal` -> BLOCK self_name

Delivered (evaded) attempts:
- `my name is ujjxxal` then `xx = w`  (user-defined substitution cipher)
- `my name is \n\nu\nj\nj\nw\na\nl`  (name spelled one letter per line)

The working leak was the newline-spelled name. The same hole applies when the
letters are sent as separate messages (the cross-message window reuses the same
matcher).

## 2. Root cause (a real Veil bug, not just a missing feature)

Self-name Tier 2 ("glued" match, `LeakGuard._self_name`) compares:
- needle = `normalize.collapse_all(name_token)`
- haystack = `normalize.collapse_all(raw_message)`

`collapse_all` runs `fold_primary`, which includes `squeeze_letters`
(`([a-z])\1+ -> \1`). The squeeze is applied asymmetrically:

- Needle `ujjwal` -> squeeze `jj`->`j` -> **`ujwal`**
- Haystack `u\nj\nj\nw\na\nl` -> newlines fold to spaces, separators stripped,
  but the two `j`s were never adjacent, so they are NOT squeezed -> **`ujjwal`**
- `ujwal` not in `...ujjwal...` -> **miss**

So any name containing a doubled letter (Ujjwal, Aakash, Neel, Rishii, Saanvi,
...) evades self-name detection once it is spelled with separators (spaces,
newlines, dots, dashes, one-letter-per-message). Names without a doubled letter
are already caught (`a k a s h` -> `akash` == needle `akash`).

Two independent weaknesses fall out of this, which map to the two fixes:
1. The double-letter squeeze asymmetry itself (Fix A).
2. No dedicated handling of the spelling PATTERN, and the length floor
   (`_SELF_NAME_GLUE_MIN = 6`) means short names spelled out are never caught,
   even without a doubled letter (Fix B).

## 3. Scope: caught vs missed today

| Form | Example | Today |
|------|---------|-------|
| direct / boundary | `My name is Ujjwal` | BLOCK (Tier 1) |
| spaced, no double, len>=6 | `a k a s h` | BLOCK (Tier 2) |
| spaced/newline, doubled letter | `u j j w a l` | **MISS** (Fix A) |
| spaced, short name (<6) | `a r y a` (Arya) | **MISS** (Fix B) |
| reversed + doubled, spelled | `l a w j j u` | **MISS** (Fix A/B parity) |
| `ujjxxal` + `xx = w` cipher | - | MISS (out of scope, Section 6) |
| doubled name across separate msgs | `U` `J` `J` ... | **MISS**; after fixes, completing msg blocks (Section 5) |

---

## 4. Fix A - double-letter symmetry in self-name (zero-FP)

Make the collapsed self-name comparison double-letter symmetric by adding an
UN-squeezed collapsed view alongside the existing squeezed one, and matching if
the name appears in EITHER.

- `haystack_raw` = strip non-alnum from `fold_base(raw)`. `fold_base` does NFKC +
  invisible strip + confusables + lower + accent-fold + whitespace->space, but
  NO squeeze and NO de-glue. For the case above: `mynameisujjwal`.
- `needle_raw` = strip non-alnum from `fold_base(name_token)` = `ujjwal`.
- Hit if `needle_raw in haystack_raw` for tokens `>= _SELF_NAME_GLUE_MIN` (6).
- Keep the current squeezed path too, so stretch (`ujjwaaal`, `himaaanshu`)
  still matches. Final Tier-2 rule: match in the squeezed OR the raw view.
- Apply the same squeezed-OR-raw pair to Tier 3 (reversed name) so a reversed
  doubled name is handled with the same symmetry.

Why zero-FP (same guarantees as current Tier 2):
- Self-name only: only the sender's own name tokens, only ever blocks the sender;
  a partner is never blocked.
- Distinctive tokens only (len >= 6), unbounded substring, exactly as today.
- Dropping the squeeze can only ADD matches where the literal doubled name is
  present. The literal form is MORE specific than the squeezed form, so FP risk
  is <= current.

Covers: doubled-letter name spelled with any separator in a single message
(the observed leak), and the completing-message block in the cross-message
window (which reuses this matcher).

## 5. Fix B - dedicated spelled-out-name detector (zero-FP), catches SHORT names

Fix A still relies on the `>= 6` length floor (needed to keep an unbounded
substring match FP-free). A short name spelled out (`a r y a` -> Arya,
`r a v i` -> Ravi) stays invisible. Fix B closes that by using the spelling
STRUCTURE itself as the false-positive gate, which lets us safely match shorter
names.

Detector (new, own name `self_name_spelled` for telemetry):
1. Tokenise the message (and, for the window path, the concatenated window) into
   whitespace/punctuation-separated tokens on the `fold_base` view.
2. Find a contiguous RUN of single-character alphanumeric tokens (letters spelled
   one at a time; filler words like `my name is` break the run and are skipped,
   so we scan each maximal run).
3. Concatenate the run into a candidate string (doubles preserved - no squeeze).
4. If the candidate CONTAINS a sender-name token (compared with Fix A's raw,
   un-squeezed form) AND the run length is `>=` that name token's length, emit a
   `SELF_NAME` hit.

Zero-FP rationale:
- A contiguous run of single-letter tokens is itself abnormal in ordinary prose;
  that abnormal structure is the gate, so we no longer need the `>= 6` floor.
- Must contain the SENDER's own name and only blocks the sender. Initialisms and
  interjections spelled out (`b t w`, `o m g`, `g g`) spell other words, never
  the sender's name, so they never match.
- Requiring run length `>=` name length means the full name is actually present
  as a contiguous spelled run, not inferred from scattered letters.

Covers: short names spelled out (any separator), and gives a clean, auditable
detector + corpus coverage distinct from the Tier-2 substring path. Also runs on
the window-concatenated text, so a short name dripped across messages blocks on
the completing message (same free improvement as A; the earlier-letters
limitation in Section 6 still applies).

Note on relationship to A: A is the correctness fix for the existing `>= 6`
substring matcher (doubled letters). B is a new, narrower structural detector for
the spelled-out pattern that additionally reaches short names. They overlap on
`u j j w a l` (either would catch it) and are complementary elsewhere; shipping
both gives defence in depth with no added FP surface.

---

## 6. Out of scope (NOT doing now, per owner)

- **Hard cross-message residual (the partial-delivery problem).** When letters
  are sent as truly separate messages, A/B block the COMPLETING message, but
  letters 1..n-1 were each harmless and already delivered, so the partner can
  read `UJJWA` and infer the name. Veil cannot un-deliver prior messages. The
  only ways to catch it earlier are (a) hard-blocking single-character messages
  (unacceptable false positives: `k`, `y`, `n`, a lone emoji) or (b) an
  admin-only suspicion signal. Both are explicitly deferred.
- **Decoding user-defined ciphers** (`ujjxxal` + `xx = w`). Unbounded variants,
  unbounded false positives.
- **Hard-blocking single-character messages.** FP explosion, and it cannot
  recover already-delivered letters.

## 7. Validation (before ship)

- New unit / corpus cases:
  - doubled-letter name spelled with spaces, newlines, dots, dashes, and
    one-letter-per-message -> BLOCK (single message); completing msg blocks
    (window). [Fix A]
  - short name spelled out (`a r y a`, `r a v i`) -> BLOCK. [Fix B]
  - non-doubled name spelled, len>=6 -> still BLOCK (regression guard).
  - stretch (`ujjwaaal`, `himaaanshu`) -> still BLOCK (squeezed path intact).
  - reversed doubled name spelled -> BLOCK. [Fix A/B parity]
  - partner typing the same letters -> NOT blocked (self-name is sender-only).
  - `b t w`, `o m g`, `g g`, `a b c d`, and ordinary prose with incidental
    single letters -> no FP.
- Run the zero-FP corpus gate (`apps/privacy/tests/test_corpus.py`) and the full
  privacy suite; both must stay green.
- Bump `RULESET_VERSION`.

## 8. Recommendation

Ship Fix A and Fix B together. Both are Veil-side, single-scan (single message or
window concatenation), and preserve the zero-false-positive guarantee. A corrects
the real double-letter bug; B adds a dedicated spelled-out detector that also
reaches short names. The cross-message partial-delivery residual and cipher
decoding are deferred (Section 6).
