# Muffle — Profanity Softening Engine (Plan)

> Status: **Implemented (BE v1) — 2026-10-10.** Scanner, tiered ruleset, service,
> `send_text` wiring, `ProfanityEvent`, and tests all landed locally (full suite
> green). Not yet committed/deployed.
> Author: backend. Written: 2026-10-10.
> Sibling of **Veil** (`docs/VEIL_ENGINE_PLAN.md`). Lives in `apps/privacy/`.

**Name:** **Muffle** — it muffles harsh language rather than silencing people. Core
component: `MuffleGuard`. Alt names: *Bleep, Grawlix, Decorum, Softener.*

**One-line contrast with Veil (important):**

| | Veil | **Muffle** |
|---|---|---|
| Target | Contact / PII leakage | Harsh / abusive profanity |
| Action | **BLOCK** (message not sent) | **MASK** (message *is* sent, word partially censored) |
| Output | nothing persisted | masked text persisted + broadcast |

So "curse blocking" is really **curse *masking*** — the message goes through; only
the offending word is softened.

**No AI.** Deterministic: tiered dictionaries + the shared Veil normaliser
(leet / stretched-letters / spacing) + a word-boundary guard. A cost-bounded
AI/human layer is an optional future seam, not a v1 need.

---

## 1. The core idea — tiers, not a flat blocklist

The whole point is that **mild, casual swearing stays untouched** (it's how college
students actually talk), while **aggressive, targeted, or identity-based** language
gets softened. Presence of a "bad word" is not enough — *which tier* it's in decides
what happens.

| Tier | What's in it | Action (default) | Example |
|---|---|---|---|
| **T0 — Casual** | mild, non-targeted expletives used for emphasis | **ALLOW** (no change) | `fuck`, `shit`, `damn`, `crap`, `ass`, `hell`, `bloody`, `wtf` |
| **T1 — Harsh / targeted** | strong vulgarity, compound escalations, sexual/family-targeted insults (incl. strong Hinglish gaalis) | **MASK** (sparse partial) | `motherfucker` → `mo*he*fu*ker` |
| **T2 — Slur / hate** | identity-based slurs: caste, religion, race, gender, orientation, disability | **MASK + FLAG** (log for T&S; action configurable) | *(not enumerated here — see §5)* |

- The **T0 ↔ T1 boundary is the crux** and is a product/values decision — it's fully
  config-driven so the owner tunes it. Default above is a starting point.
- **T2 (slurs) recommendation:** you asked to *mask*; slurs are hate speech and
  arguably deserve more. Default = **mask + flag** (record a `LeakEvent`-style row
  for admin review, reusing Veil's strike/escalation plumbing). Whether T2 should
  instead **block** (like Veil) is a one-line config flip — flagged for your call.

---

## 2. Masking scheme — *sparse* partial (keep it readable)

You want light masking, not the whole middle blanked (`m**********r`). So Muffle
masks a **deterministic subset** of interior characters — never the first or last —
leaving the word recognisable:

- Keep first and last character.
- Mask letters at a fixed **stride of 3**, starting at the 3rd character.
- Never mask a word ≤ 3 chars (and those are T0 anyway).

```
motherfucker            -> mo*he*fu*ker
<keep m,o> *(t) <h,e> *(r) <f,u> *(c/k) <...> <keep last>
```

- **Stretched / obfuscated inputs** (`motherfuuucker`, `m0th3rfucker`) are matched
  on a normalised view but **masked on the original text** at the mapped offsets, so
  the user's styling is preserved and only a few chars become `*`.
- Masking character, stride, and "min visible fraction" are all config (default `*`,
  stride 3, keep ≥ ~60% visible).

---

## 3. Detection pipeline

```
raw message
  → [A] Normalise (SHARED with Veil's LeakGuard: NFKC, zero-width strip, leet fold,
        stretched-letter collapse "fuuuck"->"fuck", spacing "f.u.c.k"->"fuck")
        — while keeping an offset map back to the ORIGINAL text
  → [B] Match tiered dictionaries with WORD BOUNDARIES (+ whitelist)
  → [C] Decide per match: T0 allow / T1 mask / T2 mask+flag
  → [D] Rewrite: apply sparse partial mask to original spans; return new text + hits
```

### [B] Dictionaries (tiered, versioned, India-aware)
- **English** T0 / T1 / T2 lists, seeded from curated open sources (e.g. LDNOOBW
  "naughty words", Surge obscenity list) then **re-tiered by us** (the tiering is the
  value, not the raw list).
- **Hinglish + Devanagari** T1 / T2 — essential for this audience (maa/behen-family
  gaalis, caste/communal slurs), seeded from HASOC / HinTox-style resources. Matched
  in both Latin transliteration and `देवनागरी`.
- Compiled to an **Aho-Corasick** automaton for O(n) matching; whole-word only.

### Scunthorpe guard (false-positive control)
The classic failure mode is masking clean words that *contain* a bad substring
(`class`, `assassin`, `Scunthorpe`, `cockpit`, `pass`, `Dick`/`Richard` as a name).
Defence:
1. **Word-boundary matching** (not substring).
2. A **whitelist** of known-clean words that embed a flagged substring — checked
   first; whitelisted words are never masked.
3. Backward/forward scan to confirm the flagged token isn't enclosed in a longer
   clean word.

---

## 4. Backend design (ties into the pipeline)

- Lives in **`apps/privacy/`** alongside Veil; **reuses the LeakGuard normaliser**
  (refactor the normaliser into a shared helper both scanners import).
  - `services/muffle_guard.py` → `MuffleGuard.scan(text) -> MuffleResult{masked_text, hits}` (pure, testable).
  - `services/muffle_service.py` → orchestrates flag/mode + persistence + T2 flagging.
  - `ruleset_profanity.py` → versioned tier lists + whitelist + `export()` for FE.
- **Pipeline order in `send_text`:** **Veil first** (may BLOCK). If allowed, **Muffle
  rewrites** `content` → persist and broadcast the **masked** text. (Veil blocks;
  Muffle only transforms.)
- **Persistence:** the masked text becomes the canonical `Message.text_content`.
  Per the same temporary policy as Veil (§7 of its plan), **store the original** on a
  `ProfanityEvent` row for admin review (category, tier, rule_version, raw original,
  masked output) — revisit redaction later.
- **T2 flagging:** reuse Veil's `LeakStrike`/escalation so repeated slur use can
  escalate to T&S (no auto-ban in v1).
- **Config & flags:** `FeatureFlagKey.MUFFLE_ENABLED`; `AppConfigKey` for
  `MUFFLE_MODE` (`shadow` | `mask`), mask char, stride, per-tier action map, and the
  ruleset version. **Shadow mode** logs would-be masks without changing text, for
  tuning.
- **Performance:** compiled automaton + precompiled regex; O(n), in-process, fits the
  synchronous `send_text` path. No extra round-trips.

## 5. On listing slurs (deliberately not in this doc)

This plan intentionally does **not** enumerate T2 slurs. They'll live in a
curated, access-controlled `ruleset_profanity.py` seeded from the open datasets
above and reviewed by the owner — the doc states the *categories* and *policy*, not
the words. T0/T1 examples are shown only to illustrate the tier boundary.

## 6. Frontend (light — server-authoritative)

Because Muffle **rewrites the message server-side**, the client mostly just
**renders the masked text** it receives over REST/WS — far less FE work than Veil.
Optional niceties (for FE to consider, later): a one-time "we soften harsh language"
note, and (if desired) mirroring the ruleset for a live compose-time preview. The
server is always the source of truth.

## 7. Tuning, rollout & limits

- **Rollout:** (0) build `MuffleGuard` + tier lists + whitelist + red-team tests →
  (1) **shadow mode** (log would-mask, measure FPs) → (2) enable masking (T0 allow /
  T1 mask / T2 mask+flag) → (3) expand Hinglish/Devanagari lists; tune tiers.
- **False-positive control:** word boundaries + whitelist + shadow-mode review of
  `ProfanityEvent` logs; the T0 "allow" tier itself is the biggest FP reducer.
- **Metrics:** mask rate, per-tier and per-word hit counts, whitelist saves, T2 flag
  count, FP reports.
- **Honest limits:** creative spellings and brand-new slang will slip (dictionaries
  always lag); the sparse mask is a *civility nudge*, not a guarantee; tiering is a
  values call that will need periodic review. This matches industry practice.

## 8. Artifacts (when we build)

- `apps/privacy/services/muffle_guard.py` + `muffle_service.py`.
- `apps/privacy/ruleset_profanity.py` (tiered lists + whitelist, versioned).
- `ProfanityEvent` model (+ reuse `LeakStrike`).
- Red-team corpus incl. **Scunthorpe cases** (`class`, `assassin`, `cockpit`, names).
- `docs/MUFFLE_SPEC.md` freezing the tier→action contract + masking algorithm.

---

## 9. Phrase detection (v1.1) — detailed design

**Why:** v1 is word-by-word, so multi-word profanity (`son of a bitch`, `piece of
shit`, Hinglish `teri maa ki ...`) slips through — each word is either clean or
sits in T0. We add **tiered multi-word phrase matching** with the SAME sparse mask,
applied **across the whole phrase span** (per owner: `son of a bitch` → `so* o* a
bi*ch`).

### 9.1 Ruleset additions (`ruleset_profanity.py`)
- New tiered **phrase** lists (only the actioned tiers need listing; anything not
  listed is allowed):
  - `T1_PHRASES` — harsh, masked. e.g. `son of a bitch`, `piece of shit`,
    `fuck you`, `fuck off`, `go fuck yourself`, `shut the fuck up`, `suck my dick`,
    `eat shit`; Hinglish `teri maa ki`, `teri maa ka`, `maa ki`, `behen ke laude`,
    `teri behen ki`.
  - `T2_PHRASES` — slur/hate phrases, masked **and** flagged (seeded from the
    curated list during review; not enumerated here).
- Each phrase stored **normalised**: lowercase, single-spaced, no punctuation.
- Reuse existing `MASK_CHAR` / `MASK_STRIDE` / `MASK_START`. Add `MIN_PHRASE_WORDS = 2`.
- **Bump `RULESET_VERSION`.** Add `t1_phrases` to `export()`; **omit `t2_phrases`**
  from the client export (same policy as T2 words — masking is server-authoritative).
- **Tier boundary is a values call** (e.g. "son of a bitch" could be T0/allowed).
  Ship a conservative default; owner tunes.

### 9.2 Matching algorithm (`muffle_guard.py`)
Token-sequence matching over the existing word tokens — this gives clean word
boundaries **and** exact original-offset spans for masking, and naturally tolerates
separators between words (`fuck, you` still matches `fuck you`).

1. Tokenise once: `tokens = [(folded, start, end)]` from `_WORD_RE.finditer(text)`
   (`folded` = NFKC + zero-width strip + lower + leet, as today).
2. Precompile each phrase to a **list of per-word stretch-regexes** (`f+u+c+k+ …`,
   so `fuuuck you` / `f1sh` leet still match), tagged with tier, **bucketed by first
   word** for fast lookup.
3. Single left-to-right pass with **longest-/most-severe-match-first**:
   ```
   i = 0
   while i < len(tokens):
       hit = best phrase starting at token i   # prefer T2 > T1, then longer
       if hit:
           span = (tokens[i].start, tokens[i+len-1].end)
           mask text[span] with sparse_mask(); record MuffleHit(kind=phrase)
           i += len(hit)                       # consume the phrase's tokens
       else:
           classify tokens[i] as a single word (existing logic); i += 1
   ```
   Running **phrases first and consuming their tokens** prevents double-processing
   (a word inside a matched phrase isn't re-masked).
4. **Masking across the span:** reuse `sparse_mask()` on the original phrase
   substring. It masks every Nth *alphabetic* char and skips the first/last and all
   non-letters, so interword spaces/commas are preserved:
   `son of a bitch` → `so* o* a bi*ch`.

### 9.3 Edge cases / FP control
- **Idiomatic-but-mild phrases** stay safe by simply not being in `T1_PHRASES`
  (tiering is the control, same as words).
- **Overlap** (phrase contains a T0/T1 word): phrase wins; its tokens are consumed.
- **Punctuation between words** handled (token list ignores separators; the masked
  span still covers them).
- **Performance:** first-word bucketing → O(tokens × phrases-in-bucket × phrase-len);
  negligible for chat-length text.
- **Known gap (unchanged):** profanity broken *inside* a word by separators
  (`f.u.c.k`) still isn't matched; that's a separate normalisation item.

### 9.4 Changes required
- `ruleset_profanity.py`: add `T1_PHRASES` / `T2_PHRASES` + `MIN_PHRASE_WORDS`,
  bump version, extend `export()`.
- `muffle_guard.py`: phrase compilation + the phrase-first pass; `MuffleHit` gains a
  `kind` (`word`|`phrase`). `MuffleResult`/`MuffleService`/`ProfanityEvent` and the
  `send_text` wiring are **unchanged** (phrases flow through the same path; `words`
  on the event will list matched phrases too).
- Tests: phrase masking + exact sparse output, longest/most-severe precedence,
  phrase-first vs single-word overlap, leet-in-phrase, Hinglish phrase, and FP
  (an allowed idiomatic phrase left untouched).
- No model, migration, config, or FE-contract changes.
