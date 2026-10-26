"""SuspicionGuard — the non-blocking "second-hand Veil" scanner.

Pure, dependency-light (no DB, no cache, no network): given a message string (and,
for the behavioral signals, the sender's recent messages) it returns a
:class:`SuspicionVerdict` of weighted, CLASSED soft signals. It NEVER blocks and is
NEVER shown to the user; ``SuspicionService`` persists the result for admin review
and for tuning Veil.

Every signal here is a variant that LEAKS PII but which Veil cannot hard-block
without risking a false positive (so it would hinder legitimate users). Veil keeps
the certain cases; these sub-threshold / ambiguous cousins land here. See
docs/VEIL_AND_SUSPICION_MASTER_PLAN.md section 4.

Signal classes (suspicion_data.SIGNAL_CLASS):
  ambient     NON_LATIN_SCRIPT, ROMANIZED_INDIC, GIBBERISH  (normal for this user
              base; recorded but EXCLUDED from the ranking/tier score)
  structural  OBFUSCATION_INVISIBLE / _SPLIT / _LEET
  pii         NEAR_PHONE, PARTIAL_DIGITS, DIGIT_DENSITY, BRAND_MENTION, HANDLE_SOFT,
              SELFNAME_SOFT, REVERSAL_HINT, CONTACT_SOFT, ENTROPY_TOKEN
  behavioral  DIGIT_DRIP, CHAR_BURST, CROSS_MESSAGE  (BLOCKED_LEAK is injected by
              the service when Veil hard-blocked the message)

Reuses the Veil normalisation views, ruleset, and digit reassembler so the two
engines see text the same way.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from apps.privacy import normalize, ruleset
from apps.privacy.dictionaries import SPELLED_DIGITS
from apps.privacy.services.leakguard import (
    extract_digits,
    extract_leet_digits,
    looks_like_phone,
)
from apps.privacy.suspicion_data import (
    BRAND_WORDS,
    COLLISION_DIGITS,
    COMMON_BIGRAMS,
    CONTACT_INTENT_MARKERS,
    DEFAULT_SIGNAL_WEIGHTS,
    GIBBERISH_ALLOWLIST,
    NON_LATIN_RANGES,
    REVERSAL_CUES,
    ROMANIZED_INDIC_MARKERS,
    VOWELS,
    ZERO_WIDTH_CODES,
)

_WORD_RE = re.compile(r"[a-z0-9]+")
_DIGIT_RUN_RE = re.compile(r"\d+")
_LEET_CHARS = set("o0i1l2z3e4a5s7b8g9q@$")
# A token split by separators into >=4 single-char groups ("h.e.l.l.o", "9-8-7-6").
_SPLIT_TOKEN_RE = re.compile(r"(?:[a-z0-9][^a-z0-9\s]){3,}[a-z0-9]")
# A brand word followed by a connector then a letters-only value ("my insta is cool").
_BRANDS_RE = r"(?:" + "|".join(sorted(BRAND_WORDS, key=len, reverse=True)) + r")"
_HANDLE_SOFT_RE = re.compile(
    r"\b" + _BRANDS_RE + r"\b\s*(?:is|id|handle|user(?:name)?|:|-|=|~|@)\s*([a-z]{3,})"
)


@dataclass(frozen=True, slots=True)
class SuspicionSignalHit:
    signal: str
    weight: int
    span: str


@dataclass(frozen=True, slots=True)
class SuspicionVerdict:
    signals: tuple[SuspicionSignalHit, ...]
    score: int
    top_signal: str | None


class SuspicionGuard:
    """Deterministic non-blocking soft-signal scanner."""

    def scan(
        self,
        text: str,
        *,
        sender_name: str = "",
        prior_messages: tuple[str, ...] = (),
        weights: dict[str, int] | None = None,
    ) -> SuspicionVerdict:
        raw = text or ""
        w = weights or DEFAULT_SIGNAL_WEIGHTS
        fp = normalize.fold_primary(raw)
        collapsed = normalize.collapse_all(raw)

        found: dict[str, SuspicionSignalHit] = {}

        def emit(signal: str, span: str) -> None:
            if signal not in found:  # each signal fires at most once (first span wins)
                found[signal] = SuspicionSignalHit(signal, int(w.get(signal, 1)), span)

        self._ambient(raw, fp, sender_name, emit)
        self._structural(raw, emit)
        self._digits(raw, emit)
        self._contact(fp, collapsed, emit)
        self._self_name(collapsed, sender_name, emit)
        self._entropy(fp, emit)
        self._behavioral(raw, prior_messages, emit)

        hits = tuple(found.values())
        score = sum(h.weight for h in hits)
        top = max(hits, key=lambda h: h.weight).signal if hits else None
        return SuspicionVerdict(signals=hits, score=score, top_signal=top)

    # -- ambient ------------------------------------------------------------
    @staticmethod
    def _ambient(raw, fp, sender_name, emit) -> None:
        for ch in raw:
            cp = ord(ch)
            for lo, hi in NON_LATIN_RANGES:
                if lo <= cp <= hi:
                    emit("NON_LATIN_SCRIPT", ch)
                    break
            else:
                continue
            break
        tokens = _WORD_RE.findall(fp)
        markers = [t for t in tokens if t in ROMANIZED_INDIC_MARKERS]
        if markers:
            emit("ROMANIZED_INDIC", " ".join(markers[:5]))
        name_tokens = {t for t in _WORD_RE.findall((sender_name or "").lower())}
        for tok in tokens:
            if (
                tok.isalpha()
                and len(tok) >= 5
                and tok not in GIBBERISH_ALLOWLIST
                and tok not in name_tokens
                and _is_gibberish(tok)
            ):
                emit("GIBBERISH", tok)
                break

    # -- structural (obfuscation mechanics) ---------------------------------
    @staticmethod
    def _structural(raw, emit) -> None:
        if any(ord(c) in ZERO_WIDTH_CODES for c in raw):
            emit("OBFUSCATION_INVISIBLE", "zero-width")
        lowered = raw.lower()
        if lowered.translate(ruleset.CONFUSABLES_TABLE) != lowered:
            emit("OBFUSCATION_INVISIBLE", "confusable")
        m = _SPLIT_TOKEN_RE.search(lowered)
        if m is not None:
            emit("OBFUSCATION_SPLIT", m.group(0))
        singles = 0
        for tok in raw.split():
            if len(tok) == 1 and tok.isalnum():
                singles += 1
                if singles >= 4:
                    emit("OBFUSCATION_SPLIT", "spaced-letters")
                    break
            else:
                singles = 0
        # Heavy leet density: a long alpha-ish token that is mostly leet characters
        # (gamer-speak, or a disguised word/number) without being a Veil hit.
        for tok in _WORD_RE.findall(lowered):
            if len(tok) >= 5 and sum(c in _LEET_CHARS for c in tok) >= 3 \
                    and any(c.isdigit() for c in tok) and any(c.isalpha() for c in tok):
                emit("OBFUSCATION_LEET", tok)
                break

    # -- pii: digits --------------------------------------------------------
    def _digits(self, raw, emit) -> None:
        prefolded = normalize.prefold_numeric(raw)
        near = False
        for m in _DIGIT_RUN_RE.finditer(prefolded):
            if 6 <= len(m.group(0)) <= 9:
                emit("NEAR_PHONE", m.group(0))
                near = True
                break
        all_digits = extract_digits(raw)
        leet_digits = extract_leet_digits(raw)
        # 10+ digits that are NOT a valid mobile (Veil would already block a valid
        # one): wrong-prefix number, account/order id, Aadhaar fragment, etc.
        for cand in (all_digits, leet_digits):
            if len(cand) >= 10 and not looks_like_phone(cand):
                emit("NEAR_PHONE", cand[:16])
                near = True
                break
        if not near:
            digit_chars = sum(ch.isdigit() for ch in prefolded)
            if digit_chars >= 7:
                emit("DIGIT_DENSITY", str(digit_chars))
        # Partial spelled digits: several number words that do not complete a phone.
        tokens = _WORD_RE.findall(normalize.fold_primary(raw))
        unamb = [t for t in tokens if t in SPELLED_DIGITS]
        collide = [t for t in tokens if t in COLLISION_DIGITS]
        if len(unamb) >= 3 or (len(unamb) >= 1 and len(unamb) + len(collide) >= 4):
            emit("PARTIAL_DIGITS", " ".join((unamb + collide)[:6]))

    # -- pii: contact / brand ----------------------------------------------
    @staticmethod
    def _contact(fp, collapsed, emit) -> None:
        for tok in _WORD_RE.findall(fp):
            if tok in BRAND_WORDS:
                emit("BRAND_MENTION", tok)
                break
        m = _HANDLE_SOFT_RE.search(fp)
        if m is not None:
            emit("HANDLE_SOFT", m.group(0))
        for marker in CONTACT_INTENT_MARKERS:
            if marker in fp or marker.replace(" ", "") in collapsed:
                emit("CONTACT_SOFT", marker)
                break

    # -- pii: self-name (sub-threshold forms Veil does not hard-block) ------
    @staticmethod
    def _self_name(collapsed, sender_name, emit) -> None:
        if not sender_name:
            return
        tokens = {
            t for t in _WORD_RE.findall(sender_name.lower()) if len(t) >= 3
        }
        devoweled_hay = "".join(c for c in collapsed if c not in VOWELS)
        for tok in tokens:
            # Reversed 4-5 char name (Veil hard-blocks reversed names >= 6).
            if 4 <= len(tok) <= 5 and tok[::-1] in collapsed:
                emit("SELFNAME_SOFT", tok + " (reversed)")
                return
            # Disemvowelled 6+ char name whose full form is NOT present (else Veil
            # caught it), e.g. "hrdk" for "hardik", "hmnsh" for "himanshu".
            if len(tok) >= 6 and tok not in collapsed:
                skel = "".join(c for c in tok if c not in VOWELS)
                if len(skel) >= 4 and skel in devoweled_hay:
                    emit("SELFNAME_SOFT", tok + " (disemvowelled)")
                    return
        # Reversal cue words near name/brand content.
        pass

    # -- pii: entropy / reversal -------------------------------------------
    @staticmethod
    def _entropy(fp, emit) -> None:
        for cue in REVERSAL_CUES:
            if cue in fp:
                emit("REVERSAL_HINT", cue)
                break
        for tok in _WORD_RE.findall(fp):
            if len(tok) >= 5 and tok[::-1] in BRAND_WORDS:
                emit("REVERSAL_HINT", tok)
                break
        for tok in _WORD_RE.findall(fp):
            if (
                len(tok) >= 16
                and any(c.isdigit() for c in tok)
                and any(c.isalpha() for c in tok)
                and len(set(tok)) / len(tok) > 0.5
            ):
                emit("ENTROPY_TOKEN", tok[:20])
                break

    # -- behavioral (cross-message / cadence) ------------------------------
    @staticmethod
    def _behavioral(raw, prior_messages, emit) -> None:
        msgs = [m for m in list(prior_messages) + [raw] if m is not None]
        single_chars = 0
        single_digits = 0
        for m in msgs:
            s = (m or "").strip()
            if len(s) == 1 and s.isalnum():
                single_chars += 1
                if s.isdigit():
                    single_digits += 1
            elif s.lower() in SPELLED_DIGITS:
                single_digits += 1
        if single_chars >= 4:
            emit("CHAR_BURST", f"{single_chars} single-char messages")
        if single_digits >= 4:
            emit("DIGIT_DRIP", f"{single_digits} single-digit messages")
        if prior_messages:
            joined = " ".join(m for m in msgs if m)
            combined = extract_digits(joined)
            current = extract_digits(raw)
            if 7 <= len(combined) <= 9 and len(current) < len(combined) \
                    and not looks_like_phone(combined):
                emit("CROSS_MESSAGE", combined)


def _is_gibberish(tok: str) -> bool:
    """Conservative gibberish heuristic over a single alphabetic token (len>=5).
    Flags clear keyboard-mash / nonsense while leaving real (even unusual) words
    alone. 'y' counts as a vowel so words like 'rhythm' are not flagged."""
    has_vowel = any(c in VOWELS for c in tok)
    if not has_vowel and len(tok) >= 6:
        return True
    run = best = 0
    for c in tok:
        if c in VOWELS:
            run = 0
        else:
            run += 1
            best = max(best, run)
    if best >= 6:
        return True
    pairs = [tok[i : i + 2] for i in range(len(tok) - 1)]
    if pairs:
        common = sum(1 for p in pairs if p in COMMON_BIGRAMS)
        if common / len(pairs) < 0.15:
            return True
    return False
