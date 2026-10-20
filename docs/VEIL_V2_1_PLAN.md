# Veil v2.1 — evasion hardening (implemented)

Closes three evasions on top of v2 (`VEIL_V2_PLAN.md`): **space-stripping**,
**misspelling / stretch**, and **splitting across messages**. Deterministic, no
AI, no external API, in-process. Enforcement model unchanged (ALLOW/BLOCK/
ESCALATE, shadow/enforce, fail-open, single `send_text` chokepoint).

## Normalization views (`apps/privacy/normalize.py`, shared)
- `fold_base` — NFKC + zero-width + confusables + lower + single-space. Used by
  the structured PII regexes (email/URL/UPI/@handle) and self-name. **Zero blast
  radius vs v2** (structured detection unchanged).
- `fold_primary` — `fold_base` + **particle de-glue** (`thecafe→the cafe`) +
  **letter squeeze** (`instaaa→insta`, `mee→me`). Boundary-checked keyword/meeting
  view. Handles stretch and single-letter-doubling while keeping word boundaries
  (low FP).
- `collapse_all` — separator-free view, matched only against **distinctive**
  needles (phrases + single words ≥7), only when a glue signal is present.
  Defeats word-gluing (`addmeoninstagram`) without the Scunthorpe explosion.
- `prefold_numeric` — digit view; **never squeezed** (would corrupt numbers).

## Matchers (`apps/privacy/dictionaries.py`)
Two Aho-Corasick automatons built once at startup: `AUTOMATON_PRIMARY`
(boundary-checked, all needles) and `AUTOMATON_COLLAPSED` (distinctive needles,
substring). Both O(message length) per scan, independent of dictionary size.

## Scanner (`apps/privacy/services/leakguard.py`)
- A per-scan `_Context` computes each view **once** (no more 3× recompute).
- Primary view always; **collapsed view only when `_has_glue`** (a token ≥6).
- **libphonenumber only when ≥7 digits**; fast `[6-9]\d{9}` prefilter + reassembler first.
- Proximity (ASK/STEER near PLATFORM) measured in the primary view; the collapsed
  (glued) view uses **presence** of ASK/STEER + PLATFORM.
- **Cross-message window dedupe runs only when the current message did not already
  block**, and omits libphonenumber (reassembler covers cross-message phones).
- Split case is solved by v2.1 + the existing window: each fragment now yields a
  signal under the new views, so `"meet mee at"` + `"Thecafe"` → window →
  INVITE+DESTINATION → MEETING block on the completer.

## Window (`VeilService._build_window`)
Still the sender's last N sent messages from the DB, now backed by composite index
`idx_message_chat_sender_dt` (`chat, sender, -created_at`) → index-only scan.
(Redis capped-list hot path deferred — add only if profiling shows the query
dominates.)

## Dictionaries
Added glued 2-word steer/ask phrases (`add me`, `text me`, `give me`, …) so their
collapsed forms (`addme`, `textme`) match. `DISTINCTIVE_MIN_LEN = 7`.

## Guardrails
Boundary checks (primary), distinctive-only + glue-gate (collapsed), the meeting
**combination** requirement (a lone venue/time never blocks), `veil_mode` shadow
rollout. FP guards verified: `instance`, `install`, `decaffeinated`, `is the
canteen open right now` all allowed.

## Deferred
- A4 fuzzy (edit-distance) — via Levenshtein-automaton/BK-tree over curated
  distinctive needles, with a legal-word FP guard; only if the corpus shows a gap.
- Phase-0 labeled corpus + precision/recall/latency harness (recommended next).
- Redis capped-list window.
- Muffle multilingual profanity (Plan B, stashed) — will reuse `normalize.py` +
  the automaton loader.

## Status
Implemented + tested (full suite 519 green), dev DB migrated, live on local BE.
Not committed, not deployed. Deps: `phonenumbers`, `pyahocorasick`.
