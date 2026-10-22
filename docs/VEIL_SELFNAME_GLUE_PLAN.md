# Veil - glued / clubbed self-name evasion - Plan

## Report
A sender revealed their own name by gluing it inside other letters:
**"Myhimanshuself"** (sender = "Himanshu Chauhan") was NOT blocked and sent fine.

## Diagnosis (confirmed in code)
`LeakGuard._self_name` (`apps/privacy/services/leakguard.py:445`) splits the
sender's name into tokens (`himanshu`, `chauhan`) and matches each against
`fold_base` with **word-boundary anchors**:
```
re.search(r"(?<![a-z])" + re.escape(tok) + r"(?![a-z])", fold_base)
```
In `myhimanshuself` the token `himanshu` is wedged between a letter before (`y`)
and after (`s`), so both anchors fail and the guard never fires.

Note what the boundary form DOES still catch (do not regress these): the name as a
standalone word ("i am himanshu"), and the name glued to **non-letters** -
digits/punct ("himanshu123", "123himanshu") - because a digit is not `[a-z]`, so
the lookarounds still pass. The gap is specifically **letters on both sides**.

## Root cause
Self-name uses only the boundary view. Veil already has the right tool for glued
needles but self-name was never wired to it:
- `normalize.collapse_all(text)` (`apps/privacy/normalize.py:81`) = fold_base +
  particle de-glue + repeated-letter squeeze + **all separators removed**. Its
  docstring literally says "substring matching of DISTINCTIVE needles only
  (defeats word-gluing like addmeoninstagram)".
- The brand/keyword glued scan already uses it, gated by a length floor
  `_GLUE_MIN_TOKEN = 6` and a leet fold `_LEET` (leakguard.py:386-388). Self-name
  should reuse the same machinery.

Why `collapse_all` is the right haystack - it folds a huge evasion surface into one
continuous string, so a single substring test catches all of these at once:
- `Myhimanshuself` -> `myhimanshuself` (letter-glue)   [the reported case]
- `him anshu`, `h-i-m-a-n-s-h-u` -> `himanshu`          (separator-glue, de-sep)
- `himaaanshu` -> `himanshu`                            (stretch squeeze)
- `h1man5hu` -> via `_LEET` fold                        (leetspeak)
- unicode look-alikes                                   (confusables in fold_base)

## Fix (zero-FP, reuses existing gates)
Two-tier `_self_name`, change the signature to take `ctx` (needs `ctx.raw` +
`ctx.fold_base` + `ctx.sender_name`):

1. **Tier 1 - boundary (unchanged):** current regex on `ctx.fold_base`, all tokens
   `len >= _SELF_NAME_MIN_TOKEN (3)`. Zero regression.
2. **Tier 2 - glued substring (new):** for tokens `len >= _SELF_NAME_GLUE_MIN (6)`,
   normalise the needle into the same space (`needle = normalize.collapse_all(tok)`
   so a doubled-letter name like "Aarav" squeezes consistently) and test
   `needle in collapsed` or `needle in collapsed.translate(_LEET)`, where
   `collapsed = normalize.collapse_all(ctx.raw)`. Hit category stays
   `SELF_NAME` (`_HIGH`), reason `self_name_glued` (distinct from `self_name` for
   audit/telemetry).

Reuse `_GLUE_MIN_TOKEN` (= 6) as `_SELF_NAME_GLUE_MIN` (or alias it). `himanshu`
(8) and `chauhan` (7) both clear it.

### Why this stays zero-FP
- **Length floor 6**: short name tokens ("om", "yash", "raj") get only Tier-1
  boundary matching, never unbounded substring, so they can't fire inside common
  words. A 6+ char name token being a substring of an ordinary word is vanishingly
  rare.
- **Self-only blast radius**: self-name matches the SENDER's own name only. A false
  positive can affect at most the one user whose own name happens to be a long word
  substring, and only on their own outgoing messages - it never blocks the partner.
- No change to Tier 1, so every currently-passing benign line is unaffected.

### Optional extra guard (only if a real FP appears)
Skip a Tier-2 token that is itself a common dictionary word (small English/Hindi
stopword set). Not included by default - the length floor already covers it and a
stopword list adds FP surface of its own. Add only if the corpus flags a case.

## Corpus (`apps/privacy/tests/test_corpus.py`)
MALICIOUS (must BLOCK), sender name "Himanshu Chauhan":
- "Myhimanshuself"                      (the reported case)
- "it is himaaanshu here"               (stretch)
- "call me h i m a n s h u"             (separator glue)
- "h1man5hu this side"                  (leet)
- "chauhanhereactually"                 (second token, glued)

BENIGN (must NOT block):
- Partner (different sender) saying "himanshu" -> allowed (self-only).
- A sender whose name token is < 6 inside a word, e.g. name "Om Sharma" sending
  "coming soon" / "welcome home" -> "om" must not fire via Tier 2.
- Generic long words that are NOT the sender's name -> unaffected.
The zero-FP corpus gate must pass before deploy.

## Residual gaps (note, not in scope now)
- **Short names (< 6) glued in letters** ("heyyashhere") remain uncaught by design -
  the zero-FP floor wins over catching them. Revisit only with a curated/edit-
  distance approach if it matters.
- **Cross-message name splitting** ("myhim" then "anshuself") - the digit
  reassembler stitches phones across messages, but names are not reassembled.
  Possible phase 2; out of scope here.

## Rollout
Single-file change in `leakguard.py` (`_self_name` + one constant) plus corpus
additions. No new feature flag (folds into `veil_enabled`, per the "no per-decoder
flags" rule). No migration. Runs under live `veil_mode=enforce`; deploy = ship
`git archive main` + restart `matila-asgi`.
