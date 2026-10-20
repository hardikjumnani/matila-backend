# Veil v2 — anti-leakage engine (implemented)

Deterministic, no AI, no external API, in-process. Goal: low/no marginal cost and
low latency. This supersedes the v1 design in `VEIL_ENGINE_PLAN.md` for the parts
below; the enforcement model (ALLOW / BLOCK / ESCALATE, strict from attempt #1,
graduated tone, shadow/enforce, fail-open, single `send_text` chokepoint) is
unchanged.

## What changed in v2

1. **Phone — libphonenumber.** `phonenumbers` validates international + Indian
   numbers (`PhoneNumberMatcher`, region `IN`), on top of the fast `[6-9]\d{9}`
   prefilter over the reassembled digit string. Fewer false positives (student
   IDs, dates) and intl coverage.

2. **Multilingual keyword dictionaries.** `apps/privacy/languages.py` holds
   per-language romanized word-lists (English, Hindi/Hinglish, Tamil, Telugu,
   Kannada, Malayalam, Marathi, Bengali, Gujarati, Punjabi) for the signal
   categories: `ask_verbs` (SOLICITATION), `steer_verbs` (STEERING),
   `invite_words` (INVITE), `destination_words` (DESTINATION), `time_words`
   (TIME), `direction_words` (DIRECTIONS), `location_pin` (LOCATION_PIN), plus
   `spelled_digits` (number words per language, for the reassembler). These are
   CURATED STARTER lists — expand with native-speaker review + the per-language
   corpus. Structured PII (digits/@/domains) is language-independent and already
   covered.

3. **Aho-Corasick matching.** `apps/privacy/dictionaries.py` merges every
   language + the platform list into ONE `pyahocorasick` automaton built at
   startup. Matching is one O(message length) pass, independent of dictionary
   size — so 10 languages cost startup memory, not per-message latency. Whole-word
   / phrase boundary checks keep it Scunthorpe-safe.

4. **Meeting-coordination signal engine.** Instead of a single regex, the scanner
   combines signals: block only on an actual plan —
   `LOCATION_PIN` alone, or `INVITE + (DESTINATION|TIME|DIRECTIONS)`, or
   `DIRECTIONS + DESTINATION`. A bare `DESTINATION+TIME` ("is the canteen open
   right now") is deliberately NOT blocked (benign).

5. **Self-name block (anti-de-anonymisation).** The sender's OWN name (tokens
   >= 3 chars from `full_name`) is blocked when they type it. The partner's name
   is NEVER checked against a sender — a block must not confirm who they matched.
   `VeilService` passes `sender.full_name`; the guard matches whole-word.

6. **Cross-script confusables.** `_fold` applies a curated homoglyph map
   (`ruleset.CONFUSABLES`) for Cyrillic/Greek lookalikes NFKC does not fold
   (fullwidth/compatibility are already handled by NFKC). Curated for low FP; can
   be swapped for a full TR39 skeleton later.

7. **Cross-message window = last N SENT messages (count-based).** Replaces the
   time-TTL cache. `VeilService._build_window` reads the sender's last N
   (`VEIL_MESSAGE_WINDOW`, default 5) persisted TEXT messages in the chat, joins
   them for `prior_text`, and extracts `prior_digits`. A blocked attempt is never
   persisted, so it cannot pollute the window (replaces the old reset-on-block).
   One small indexed DB query per message.

## Enforcement outcomes
ALLOW / BLOCK / ESCALATE only (REPHRASE from the external spec rejected by the
owner). Categories: PHONE, EMAIL, UPI, URL, SOCIAL_HANDLE, PLATFORM, STEERING,
SOLICITATION, MEETING, SELF_NAME.

## Cost / latency
Per message: +~2–8 ms (dominated by the 5-message DB query; Aho-Corasick,
phonenumbers over the short digit string, confusables pass, and self-name are
each sub-ms). Startup: build automaton + load dictionaries + phonenumbers
metadata (a few hundred ms, ~10–30 MB RSS/worker). No external calls, flat/linear
scaling. See the latency/server analysis in the session notes.

## Known gaps
Images/attachments are not text-inspected (chat photos currently paused).
Deterministic detection cannot catch every implicit plan; meeting detection is
evidence-based, tuned by precision/recall. Dictionaries are starter sets.

## Files
`apps/privacy/languages.py` (per-language dicts), `dictionaries.py` (automaton +
loader), `ruleset.py` (global lists + confusables + tones + export), `enums.py`
(+MEETING, +SELF_NAME), `services/leakguard.py` (scanner), `services/veil_service.py`
(window + sender name), `constants.py` (DEFAULT_MESSAGE_WINDOW),
`apps/configuration/constants.py` (VEIL_MESSAGE_WINDOW). Deps:
`phonenumbers`, `pyahocorasick` (requirements/base.txt).
