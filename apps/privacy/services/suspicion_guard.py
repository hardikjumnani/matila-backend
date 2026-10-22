"""SuspicionGuard — the non-blocking "second-hand Veil" scanner.

Pure, dependency-light (no DB, no cache, no network): given a message string it
returns a :class:`SuspicionVerdict` of weighted soft signals. It NEVER blocks and
is NEVER shown to the user; ``SuspicionService`` persists the result for admin
assessment and for tuning Veil.

Signals (each fires at most once; score = sum of fired weights):
  - NON_LATIN_SCRIPT  letters from a non-Latin script (Devanagari/Tamil/Telugu/
                      Cyrillic/...). Could encode info or evade the Latin scanner.
  - ROMANIZED_INDIC   romanized Hindi/Tamil/Telugu function words (code-mix).
  - GIBBERISH         implausible letter sequences / keyboard mash.
  - OBFUSCATION       zero-width chars, confusables, or separator-split words.
  - NEAR_MISS         sub-threshold leak tells Veil deliberately does not block
                      (6-9 digit runs, a brand mention with no steer). Highest
                      value for improving Veil.

Reuses the Veil normalisation views and ruleset so the two engines see text the
same way.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from apps.privacy import normalize, ruleset
from apps.privacy.suspicion_data import (
    BRAND_WORDS,
    COMMON_BIGRAMS,
    DEFAULT_SIGNAL_WEIGHTS,
    GIBBERISH_ALLOWLIST,
    NON_LATIN_RANGES,
    ROMANIZED_INDIC_MARKERS,
    VOWELS,
    ZERO_WIDTH_CODES,
)

_WORD_RE = re.compile(r"[a-z0-9]+")
_DIGIT_RUN_RE = re.compile(r"\d+")
# A token split by separators into >=4 single-char groups ("h.e.l.l.o",
# "9-8-7-6"), a classic de-glue evasion.
_SPLIT_TOKEN_RE = re.compile(r"(?:[a-z0-9][^a-z0-9\s]){3,}[a-z0-9]")


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
        self, text: str, *, sender_name: str = "", weights: dict[str, int] | None = None
    ) -> SuspicionVerdict:
        raw = text or ""
        w = weights or DEFAULT_SIGNAL_WEIGHTS
        fold_primary = normalize.fold_primary(raw)

        hits: list[SuspicionSignalHit] = []
        for detector in (
            self._non_latin,
            self._romanized_indic,
            self._gibberish,
            self._obfuscation,
            self._near_miss,
        ):
            hit = detector(raw, fold_primary, sender_name, w)
            if hit is not None:
                hits.append(hit)

        score = sum(h.weight for h in hits)
        top = max(hits, key=lambda h: h.weight).signal if hits else None
        return SuspicionVerdict(signals=tuple(hits), score=score, top_signal=top)

    # -- signals ------------------------------------------------------------
    @staticmethod
    def _non_latin(raw, fold_primary, sender_name, w) -> SuspicionSignalHit | None:
        for ch in raw:
            cp = ord(ch)
            for lo, hi in NON_LATIN_RANGES:
                if lo <= cp <= hi:
                    return SuspicionSignalHit(
                        "NON_LATIN_SCRIPT", w.get("NON_LATIN_SCRIPT", 2), ch
                    )
        return None

    @staticmethod
    def _romanized_indic(raw, fold_primary, sender_name, w) -> SuspicionSignalHit | None:
        tokens = _WORD_RE.findall(fold_primary)
        markers = [t for t in tokens if t in ROMANIZED_INDIC_MARKERS]
        if markers:
            return SuspicionSignalHit(
                "ROMANIZED_INDIC", w.get("ROMANIZED_INDIC", 2), " ".join(markers[:5])
            )
        return None

    @staticmethod
    def _gibberish(raw, fold_primary, sender_name, w) -> SuspicionSignalHit | None:
        name_tokens = {t for t in _WORD_RE.findall((sender_name or "").lower())}
        for tok in _WORD_RE.findall(fold_primary):
            if not tok.isalpha() or len(tok) < 5:
                continue
            if tok in GIBBERISH_ALLOWLIST or tok in name_tokens:
                continue
            if _is_gibberish(tok):
                return SuspicionSignalHit("GIBBERISH", w.get("GIBBERISH", 2), tok)
        return None

    @staticmethod
    def _obfuscation(raw, fold_primary, sender_name, w) -> SuspicionSignalHit | None:
        # Zero-width / invisible characters.
        if any(ord(c) in ZERO_WIDTH_CODES for c in raw):
            return SuspicionSignalHit("OBFUSCATION", w.get("OBFUSCATION", 3), "zero-width")
        # Cross-script confusables (Cyrillic/Greek lookalikes folded to Latin).
        lowered = raw.lower()
        if lowered.translate(ruleset.CONFUSABLES_TABLE) != lowered:
            return SuspicionSignalHit("OBFUSCATION", w.get("OBFUSCATION", 3), "confusable")
        # Separator-split word: "h.e.l.l.o", "9-8-7-6".
        m = _SPLIT_TOKEN_RE.search(raw.lower())
        if m is not None:
            return SuspicionSignalHit("OBFUSCATION", w.get("OBFUSCATION", 3), m.group(0))
        # A run of >=4 single-character tokens ("a d d m e").
        singles = 0
        for tok in raw.split():
            if len(tok) == 1 and tok.isalnum():
                singles += 1
                if singles >= 4:
                    return SuspicionSignalHit(
                        "OBFUSCATION", w.get("OBFUSCATION", 3), "spaced-letters"
                    )
            else:
                singles = 0
        return None

    @staticmethod
    def _near_miss(raw, fold_primary, sender_name, w) -> SuspicionSignalHit | None:
        # A 6-9 digit run: phone-ish but under Veil's 10-digit floor (a real phone
        # starting 6-9 is already blocked before suspicion runs).
        prefolded = normalize.prefold_numeric(raw)
        for m in _DIGIT_RUN_RE.finditer(prefolded):
            if 6 <= len(m.group(0)) <= 9:
                return SuspicionSignalHit("NEAR_MISS", w.get("NEAR_MISS", 3), m.group(0))
        # A distinctive brand mention that did not trip a Veil block.
        for tok in _WORD_RE.findall(fold_primary):
            if tok in BRAND_WORDS:
                return SuspicionSignalHit("NEAR_MISS", w.get("NEAR_MISS", 3), tok)
        return None


def _is_gibberish(tok: str) -> bool:
    """Conservative gibberish heuristic over a single alphabetic token (len>=5).
    Flags clear keyboard-mash / nonsense while leaving real (even unusual) words
    alone. 'y' counts as a vowel so words like 'rhythm' are not flagged."""
    has_vowel = any(c in VOWELS for c in tok)
    if not has_vowel and len(tok) >= 6:
        return True
    # Longest consonant run (>=6 is extremely rare in real English words).
    run = best = 0
    for c in tok:
        if c in VOWELS:
            run = 0
        else:
            run += 1
            best = max(best, run)
    if best >= 6:
        return True
    # Fraction of adjacent letter-pairs that are common English bigrams.
    pairs = [tok[i : i + 2] for i in range(len(tok) - 1)]
    if pairs:
        common = sum(1 for p in pairs if p in COMMON_BIGRAMS)
        if common / len(pairs) < 0.15:
            return True
    return False
