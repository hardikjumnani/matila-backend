# Veil - English-only (block non-Latin scripts) - Plan

## Goal
A new HARD-BLOCK rule in the Veil ("whale") engine: a message that contains any
**non-Latin-script letter** (Devanagari/Hindi, Telugu, Tamil, Cyrillic, Greek, Arabic,
CJK, ...) is **outright blocked** (not sent). Basic-keyboard text - English letters,
numbers, punctuation, symbols - is fine.

### Important scope clarification (what is / isn't blocked)
- **Allowed:** ASCII letters/digits/punctuation/symbols, i.e. everything a basic English
  keyboard types. **Romanized Hindi/Telugu/Tamil is ALLOWED** ("kaise ho", "chalo yaar",
  "milte hain") because it's Latin letters - this rule targets SCRIPT, not language. (Veil's
  existing PII/leak detectors already scan romanized text.)
- **Blocked:** native-script letters - "नमस्ते", "హాయ్", "你好", Cyrillic "привет", and any
  message mixing them in ("hey मित्र" -> blocked). Also catches confusable evasion (Cyrillic/
  Greek look-alike letters) for free, since those are non-Latin.
- This upgrades the existing suspicion-engine `NON_LATIN_SCRIPT` SOFT signal to a HARD block.

## Detection design (deterministic, zero ambiguity)
A message is foreign-script iff it contains a character that is a **letter**
(`unicodedata.category` starts with `L`) whose code point is **outside the Latin ranges**
(Basic Latin `A-Z/a-z`, and - per decision 2 below - optionally Latin-1 Supplement /
Latin Extended for accents). Non-letters (digits, punctuation, math symbols, currency,
**emoji**, whitespace) are ignored, so the rule fires ONLY on actual foreign letters -
never on `$`, `@`, `5pm`, smart quotes, or emoji.

- Runs on the RAW text (before normalization folds confusables), so Cyrillic/Greek
  look-alikes are caught as themselves.
- Reuses the script-range data already in `apps/privacy/suspicion_data.py`
  (`NON_LATIN_RANGES`) - but the robust form is "is a letter AND not Latin", which catches
  every non-Latin script, not only the enumerated ones.

## Integration into Veil
- New `LeakCategory.NON_LATIN` (or `FOREIGN_SCRIPT`) enum value (`apps/privacy/enums.py`).
- `LeakGuard`: add a `_foreign_script(ctx.raw)` detector returning a `Hit(NON_LATIN, _HIGH,
  "foreign_script", <first offending char>)`. `_HIGH` -> the scan's action becomes BLOCK, so
  it flows through the existing block path (LeakEvent logged, user sees a block message).
- New block tone in `ruleset.TONES` (e.g. key `english`): a gentle
  "Please keep the chat in English for now." message; wire it in `VeilService._message_for`
  like the other category tones.
- **Phase gating:** Veil runs only in the ANONYMOUS phase (`message_service.send_text`), so
  the block applies pre-reveal. See decision 3 if you want English-only in ALL phases.

## Config / flag
Fold under the existing `veil_enabled` flag (no per-decoder flags, per the Veil rule). Add
ONE app-config kill-switch `veil_block_non_english` (default **true**, since you want it on)
so the policy can be toggled at runtime without a deploy if it proves too strict. Read it in
`LeakGuard`/`VeilService` the same way other config is read.

## Strike / escalation handling (decision 4)
Open question: typing one's native language is a style-policy violation, not a PII-leak
attempt. Options:
- (a) Treat like any Veil block: bump the strike counter + graduated tone (could escalate to
  a T&S flag / suspension for a user who keeps typing Hindi). Simplest, consistent.
- (b) **Recommended:** block + log a `LeakEvent` (admin visibility) but **do NOT bump the
  strike** for `NON_LATIN` - a gentle, non-punitive "English only" nudge that never
  escalates to suspension. Needs a small branch in `VeilService._inspect` to skip the strike
  for this category.

## Frontend mirror (optional, better UX)
Veil's ruleset is exported to the client (`ruleset.export()`) for a pre-send check. We can add
an "English-only" flag to that payload so the FE can block + nudge instantly before sending
(backend stays the authority). This is an AI_BRIDGE coordination item - do after you approve
the backend behavior.

## Tests / corpus (`apps/privacy/tests/test_corpus.py` + leakguard tests)
- MUST BLOCK: "नमस्ते", "హాయ్ ఎలా ఉన్నావు", "你好", "привет" (Cyrillic), "مرحبا",
  mixed "hey मित्र", a lone foreign letter in otherwise-English text.
- MUST NOT BLOCK (zero-FP): romanized "kaise ho", "chalo yaar milte hain", "great work 🔥",
  "$100 @ 5pm, see u", smart quotes / ellipsis, pure emoji, numbers/symbols. (Accented Latin
  "cafe/café" lands per decision 2.)
- Confirm the block flows end-to-end (VeilService -> MESSAGE_BLOCKED 422) and that romanized
  text + emoji still pass.

## Open decisions for the owner
1. **Emoji** - allow (recommended; heavy chat usage, and emoji aren't a script) or block?
   (Plan assumes ALLOW.)
2. **Accented Latin** (é, ñ, ü - names like "José") - allow all Latin script incl. accents
   (recommended, fewer FPs) or strict ASCII-only (blocks accents too)?
3. **Phase** - anonymous-only (recommended; reuses Veil's wiring) or English-only in ALL
   phases incl. after reveal? (All-phases needs a check outside Veil's anonymous gate.)
4. **Strike** - non-English block counts toward the suspension ladder, or block+log without
   escalating (recommended)?
5. Confirm the intent: **romanized Hindi/Telugu stays allowed**; only native scripts are
   blocked. (Plan assumes yes.)

## Rollout
One-file-ish code change (enum + LeakGuard detector + tone + optional strike branch + the
config toggle) + corpus/tests. No migration. Runs under live `veil_mode=enforce`; deploy =
ship + restart. Reversible via the `veil_block_non_english` toggle.
