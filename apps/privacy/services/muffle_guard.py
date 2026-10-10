"""MuffleGuard — the deterministic profanity scanner/masker (pure, no DB).

Tokenises the message into whole words, classifies each word into a tier on a
leet/stretch-tolerant form, and applies *sparse* partial masking to the original
span of T1/T2 words (keeping the word readable). Whole-word matching means a bad
substring inside a clean word (``class``, ``assassin``, ``cockpit``) is never hit
— the Scunthorpe guard — with the ruleset WHITELIST as a second safety net.

Known v1 gap: profanity broken up by separators ("f.u.c.k", "f u c k") splits into
separate tokens and is not matched (contiguous obfuscation like "fuuuck"/"m0ther"
IS handled). See docs/MUFFLE_PROFANITY_PLAN.md.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from apps.privacy import ruleset_profanity as rp
from apps.privacy.enums import ProfanityTier

# Normalisation (kept intentionally small; mirrors LeakGuard's digit/leet folding).
_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿­"), None)
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t"})
_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)

_T1 = ProfanityTier.T1_HARSH.value
_T2 = ProfanityTier.T2_SLUR.value
_T0 = ProfanityTier.T0_CASUAL.value


def _fold_token(token: str) -> str:
    return (
        unicodedata.normalize("NFKC", token)
        .translate(_ZERO_WIDTH)
        .lower()
        .translate(_LEET)
    )


def _stretch_pattern(word: str) -> re.Pattern:
    """A regex that matches the word with each letter stretched (fuuuck -> fuck)."""
    return re.compile("".join(re.escape(c) + "+" for c in word), re.UNICODE)


def _build_buckets(words) -> dict:
    """first-char -> [(folded_word, stretch_regex)] for fast classification."""
    buckets: dict[str, list] = {}
    for w in words:
        fw = w.lower()
        if not fw:
            continue
        buckets.setdefault(fw[0], []).append((fw, _stretch_pattern(fw)))
    return buckets


_BUCKETS = [
    (_T2, _build_buckets(rp.T2_SLUR)),
    (_T1, _build_buckets(rp.T1_HARSH)),
    (_T0, _build_buckets(rp.T0_CASUAL)),
]
_WHITELIST = {w.lower() for w in rp.WHITELIST}


@dataclass(frozen=True, slots=True)
class MuffleHit:
    word: str
    tier: str
    original: str
    masked: str


@dataclass(frozen=True, slots=True)
class MuffleResult:
    masked_text: str
    hits: tuple[MuffleHit, ...]

    @property
    def changed(self) -> bool:
        return bool(self.hits)

    @property
    def top_tier(self) -> str | None:
        if any(h.tier == _T2 for h in self.hits):
            return _T2
        if any(h.tier == _T1 for h in self.hits):
            return _T1
        return None

    @property
    def words(self) -> list[str]:
        return sorted({h.word for h in self.hits})


def _classify(token: str) -> tuple[str | None, str | None]:
    folded = _fold_token(token)
    if not folded or folded in _WHITELIST:
        return (None, None)
    first = folded[0]
    for tier, buckets in _BUCKETS:
        for word, rx in buckets.get(first, ()):
            if rx.fullmatch(folded):
                return (tier, word)
    return (None, None)


def sparse_mask(token: str) -> str:
    """Mask a deterministic ~1/3 of interior characters; keep first & last.
    e.g. 'motherfucker' -> 'mo*he*fu*ker'."""
    n = len(token)
    if n < rp.MIN_MASK_LEN:
        return token
    chars = list(token)
    for i in range(rp.MASK_START, n - 1, rp.MASK_STRIDE):
        if chars[i].isalpha():
            chars[i] = rp.MASK_CHAR
    return "".join(chars)


class MuffleGuard:
    """Deterministic profanity tiering + sparse masking."""

    def scan(self, text: str) -> MuffleResult:
        text = text or ""
        hits: list[MuffleHit] = []
        out: list[str] = []
        last = 0
        for m in _WORD_RE.finditer(text):
            tier, word = _classify(m.group(0))
            if tier in (_T1, _T2):
                original = m.group(0)
                masked = sparse_mask(original)
                hits.append(MuffleHit(word, tier, original, masked))
                out.append(text[last:m.start()])
                out.append(masked)
                last = m.end()
        out.append(text[last:])
        return MuffleResult(masked_text="".join(out), hits=tuple(hits))
