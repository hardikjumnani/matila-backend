# Veil — Privacy / Anti‑Leakage Engine (Plan)

> Status: **Plan (v1, BE implementation in progress)**
> Author: backend. Last revised: 2026‑10‑10.
> Companion specs: `REVEAL_FLOW_SPEC.md`, `COLLEGE_LAUNCH_PLAN.md`.

**Name:** **Veil** — the engine that keeps the veil of anonymity intact until a
deliberate, mutual/paid reveal. Core scanner component: `LeakGuard`. Audit rows:
`LeakEvent`.

**Why it matters for Matila:** the whole product is *anonymous until a deliberate,
paid reveal*. Every off‑app contact exchange is a **double hit** — it breaks user
safety/anonymity **and** bypasses the reveal monetisation. Veil is therefore both a
Trust & Safety control and a revenue‑protection control.

**No AI.** Deterministic rules only (regex + dictionaries + normalisation +
heuristics). Rationale: cost, latency, and predictability. A cost‑bounded AI /
human‑review layer is left as an *optional* future escalation seam, not a v1 need.

---

## 1. Threat model — what counts as "leakage"

| Category | Examples | Hard‑rule detectable? |
|---|---|---|
| **Phone numbers** | `9876543210`, `+91 98765 43210`, spelled "nine eight seven…", "double 7" | ✅ High |
| **Email** | `foo@gmail.com`, "foo at gmail dot com" | ✅ High |
| **Payment handles** | UPI VPA `name@oksbi`, "gpay me on 98…", Paytm number | ✅ High |
| **Social handles** | `@username`, "my insta is foo", "snap: foo", "add me on tg" | ✅ High |
| **External links / QR** | `linktr.ee/x`, any URL, **UPI/contact QR images** | ✅ (URLs + QR decode) |
| **Encoded numbers** | hex `0x9827…` / `9f3b`, octal `0o…`, binary `0b1001…`, digits scattered in prose | ✅ (decode → digit accumulator) |
| **Off‑app steering** | "let's move to WhatsApp", "call me", "find me on…", "let's meet at…" | ✅ Medium (intent dictionary) |
| **Soliciting PII** | "give me your ig", "send your number", "drop your snap" | ✅ High (first‑class category) |
| **Real‑name / identity reveal** | "my name is Rahul", "I'm the guy in CS dept" | ⚠️ Partial (deterrent only) |

The first eight are where hard rules shine. The last is partial — hard rules add
friction and evidence, not a perfect wall. (Even Tinder/Airbnb accept this ceiling
and backstop with reporting + human review.)

---

## 2. Design principles

1. **Deterministic & in‑process** — compiled regex + a dictionary automaton
   (Aho‑Corasick). Target **sub‑millisecond** per message, zero network calls, no AI.
2. **Normalise first, then match** — most of the difficulty is *evasion
   normalisation*, not the patterns. This is the core IP.
3. **Layered & scored** — each hit carries `{category, severity, confidence}`; a
   policy engine turns the combination into an action.
4. **Strict stop, graduated tone** — we **block the leak on attempt #1** (never
   deliver PII). What graduates with repeat offences is the *wording* shown to the
   user: polite → firmer → serious‑but‑caring.
5. **Low false‑positive bias** — **block only on high‑confidence** identifiers and
   solicitations; **allow** ambiguous low‑confidence content. Tune via shadow mode +
   admin review.
6. **Config‑driven & versioned** — the ruleset is data (JSON), not code, served to
   the client so rules can be updated without an app release.
7. **Logging (temporary policy): store raw hits.** For now we **do store the raw
   offending content** (full message + matched span) so admins can assess and judge.
   This is a deliberate temporary choice; redaction/hashing is a later revisit.
8. **India‑localised** — Indian phone/UPI formats, Hinglish dictionaries, Devanagari
   digits.

---

## 3. Detection pipeline

```
raw message
  → [A] Normaliser  → {raw, folded, compact, numeric} views (+ base‑decode)
  → [B] Detectors   → regex + dictionary + heuristics over those views
  → [C] Scorer      → aggregate hits into {category, severity, confidence}
  → [D] Policy      → ALLOW | BLOCK | ESCALATE
```

### [A] Normaliser — the evasion‑killer
Produce several views; run detectors against all of them:
- **Unicode NFKC** + strip zero‑width chars; map **homoglyphs / fullwidth / circled /
  math** letters → ASCII (`𝗂𝗇𝗌𝗍𝖺`→`insta`).
- **Leet fold**: `0→o, 1→i/l, 3→e, 4→a, 5→s, 7→t, @→a, $→s` for dictionary matching.
- **Separator → symbol**: "at the rate"/"at"→`@`, "dot"/"d0t"→`.`, "underscore"→`_`.
- **Spelled‑digit → numeral**: `one..nine`, `zero/oh→0`, **"double/triple X"**
  expansion; **Hinglish** `ek, do, teen, char, paanch, chhe, saat, aath, nau,
  shunya`; Devanagari `०–९`.
- **Base‑decode pass**: detect & decode **hex** (`0x…` or bare hex runs), **octal**
  (`0o…`), **binary** (`0b…`) into decimal digits and feed them into the numeric view.
- **Compact view**: strip spaces/punctuation/interleaved filler so `9 8-7 6 5…`
  collapses to a digit run.

### [B] Detectors
- **Indian phone:** 10‑digit starting `[6-9]`, optional `+91`/`0` prefix, tolerant of
  separators in the compact view.
- **Email:** `[\w.%+-]+@[\w.-]+\.[a-z]{2,}` plus the "x at y dot z" normalised form.
- **UPI VPA:** `^[\w.\-]{2,256}@[a-z]{2,64}$` restricted to known PSP handles
  (`oksbi, ybl, paytm, apl, ibl, axl…`) to cut FPs.
- **URLs:** scheme / `www.` / bare‑domain + TLD list; catch `linktr.ee`, shorteners.
- **@handles:** `@[a-z0-9._]{3,}` + platform‑keyword proximity.
- **Dictionary (Aho‑Corasick):** platform names (`insta/ig/snap/sc/wa/whatsapp/tg/
  telegram/discord/…`), payment (`upi/gpay/phonepe/paytm/pay me`), steering intent
  (`add me / dm me / text me / call me / find me on / my number / number de / let's
  meet / video call`), incl. Hinglish.
- **Solicitation:** phrases that *ask for* an identifier ("give me your ig / send your
  number / drop your snap", + Hinglish) — a first‑class, blockable category.
- **Number Reassembler (heuristic):**
  - From each message, **extract every number‑bearing token in order** — literal
    digits, spelled‑out (EN + Hinglish + Devanagari), "double/triple X", **and
    decoded hex/oct/bin** — and **discard all non‑numeric words**.
  - **Concatenate** into a candidate digit string; keep a **rolling per‑sender
    window** (last N messages / few minutes) so a number can be reassembled **across
    multiple messages**.
  - Test the concatenated string (and sliding substrings) for a phone shape (10‑digit
    `[6-9]`‑leading run, with/without `+91`).
  - Example: *"I saw nine sheeps, walking with eight legs, in 2 buses, under the seven
    trees…"* → extracts `9,8,2,7,…`, ignores words, trips once the run reaches phone
    length.
  - **FP guard:** a lone small number ("2 buses") never triggers; only
    **accumulation to phone length within the window** (or a strong structured match)
    does.

### [C] Scorer
Severity tiers:
- **HIGH** (structured, high‑confidence): full phone / email / UPI / URL /
  platform‑handle; **solicitation** of any identifier; an **accumulated digit‑run that
  reaches phone length** (incl. decoded/encoded).
- **MEDIUM**: steering phrase + partial identifier, or a digit run 7–9.
- **LOW**: lone platform keyword with no handle, isolated short number.

### [D] Policy → action
Action set is exactly **ALLOW · BLOCK · ESCALATE** (no WARN‑deliver, no MASK). Strict
from attempt #1; a flagged message is allowed whole or blocked whole.

| Case | Action | Message tone (graduates by offence #) |
|---|---|---|
| No hit / ambiguous LOW | **ALLOW** | — |
| Sharing PII (HIGH/MED) | **BLOCK** (don't send) | #1 gentle → #2 firmer → #3+ serious‑but‑caring |
| **Soliciting** PII | **BLOCK** (don't send) + explain why | same graduated tone |
| Repeat offenders past threshold | **ESCALATE** | hand to T&S / auto‑report / account action |

---

## 4. Backend implementation

- **New app `apps/privacy/`**
  - `services/leakguard.py` → `LeakGuardService.scan(text, *, context) -> Verdict`.
    Pure, dependency‑free, unit‑testable (normaliser + base‑decoder + reassembler +
    detectors + scorer + policy).
  - `services/veil_service.py` → orchestrates scan + persistence + strikes +
    escalation + notifications; the thing `MessageService` calls.
  - `ruleset/v1.json` + a loader — versioned patterns, dictionaries, thresholds,
    tones. Also the payload shipped to the client.
  - `models.py` → `LeakEvent`, `LeakStrike` (per‑user counter).
  - `enums.py` → `LeakCategory`, `LeakSeverity`, `LeakAction`.
- **Integration (`apps/messaging/services/message_service.py`):** scan **before**
  `Message.objects.create` in `send_text`; also gate `send_image` (QR). Branches:
  - `ALLOW` → persist + broadcast as today.
  - `BLOCK` → `ServiceResult.fail("MESSAGE_BLOCKED", <graduated message>)`; nothing
    persisted; record a `LeakEvent`.
  - `ESCALATE` → block + record + raise strike → T&S/report/account action.
- **Runs only in the ANONYMOUS phase** (ACTIVE/EXTENDED, pre‑reveal). After a
  legitimate reveal, Veil disengages — that's the reward for revealing.
- **Config & flags:** `FeatureFlagKey.VEIL_ENABLED` + `VEIL_MODE ∈ {shadow, enforce}`
  + thresholds via `ConfigurationService`. In **shadow** mode we record `LeakEvent`s
  but still deliver the message (for tuning).
- **`LeakEvent` model (stores raw for now):**
  `{chat_id, user_id, category, severity, action, rule_version, raw_message,
  matched_span, created_at}`. *(Temporary — redaction is a later revisit; principle
  #7.)*
- **Strikes & escalation (no temp‑mute):** graduated‑tone blocks → past threshold →
  **T&S review / auto‑report → account action (suspend/ban via existing
  `account_status`)**. There is **no muting step**.
- **QR / images (deterministic):** server‑side **QR decode** (`pyzbar`/OpenCV) on
  uploads → if it decodes a URL or UPI string, treat as HIGH. (Handwritten‑handle OCR
  needs heavy/AI — explicitly **out of scope v1**; known gap.)
- **Performance:** precompile regex, prebuild the Aho‑Corasick trie at startup, O(n)
  scan; fits inside the existing synchronous `send_text` path.

## 5. Frontend implementation (for FE to plan)

- **Ship the ruleset to the client** (versioned JSON: patterns + dictionaries +
  thresholds + tones), cached, refreshed on app start — BE and FE stay in sync and
  rules update without a store release.
- **Pre‑send scan in the composer** (debounced), mirroring the normaliser + HIGH/MED
  detectors for instant feedback. Posture now **matches the strict backend**: on a
  high‑confidence hit the composer **shows the polite message and does not send**; BE
  is the authoritative backstop.
- **Copy** leans into the brand and follows the gentle→serious ladder:
  *"Matila keeps you anonymous — share your insta/number after you both reveal."*
  First‑time explainer + a subtle persistent reminder during the anonymous phase.
- **Never trust the client** — FE is UX + latency; BE is truth.

## 6. Tuning, rollout & honesty about limits

- **Phased rollout:**
  0. Build scanner (normaliser + **base‑decode + Number Reassembler**) + ruleset v1 +
     **red‑team evasion corpus** + tests.
  1. BE **shadow mode**; measure precision/recall.
  2. BE **enforce (BLOCK)** + escalation + strikes.
  3. FE pre‑send scan + config delivery.
  4. QR/image, Hinglish expansion, tuning.
- **False‑positive control:** block HIGH/MED identifiers & solicitations; **ALLOW**
  ambiguous LOW; context‑gate numbers; allowlist; watch the FP‑report metric.
- **Metrics:** leak‑attempt rate, **block / escalate** counts, per‑rule hits,
  FP reports, and the north star — *off‑app‑contact complaints vs. paid‑reveal rate*.
  Admins review **logged raw hits** to tune.
- **Honest ceiling:** determined users can still evade (code words, drip across many
  messages, image text). Hard rules deliver **friction + deterrence + evidence** —
  what the industry relies on. A cost‑bounded AI/human layer for ambiguous MEDIUM
  cases is an optional later seam, not a v1 need.

## 6a. Known gaps (v1, deliberate)

- **Hinglish "2" (`do`) and other English-colliding digit words** (`do`, `oh`
  alone, `to`) are **excluded** from the spelled-digit map to keep the Number
  Reassembler's false-positive rate low. Consequence: a phone number spelled in
  Hinglish that contains a `2` won't fully reassemble. Revisit with contextual
  gating.
- **QR / image OCR**: QR decode is planned (Phase 4) but **not in the v1 code**;
  handwritten-handle OCR is out of scope (needs heavy/AI).
- **Pure-letters social handles** after a platform word (e.g. "my insta is cool")
  are not blocked (the value needs a digit/`_`/`.`), to avoid FPs on ordinary
  words. The explicit `@handle` form is always caught.
- **Escalation does not auto-ban.** It flags for T&S (audit + notification +
  `LeakEvent(action=ESCALATE)`); account actions remain an admin decision.

## 7. Artifacts

- `apps/privacy/` scanner + `ruleset/v1.json`.
- `docs/VEIL_ENGINE_SPEC.md` (freeze: `ALLOW/BLOCK/ESCALATE` contract, verdict shape,
  `LeakEvent` schema incl. raw logging, Number Reassembler behaviour).
- Red‑team test corpus (`apps/privacy/tests/`) as the regression guardrail.
