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
from collections import namedtuple
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

# --- Phrase compilation ------------------------------------------------------
# Each phrase -> (tier, [per-word stretch regexes], word_count, canonical phrase),
# bucketed by the phrase's first character. Buckets are sorted most-severe- and
# longest-first so the first match at a position is the best match.
_Phrase = namedtuple("_Phrase", "tier regexes nwords text")


def _build_phrase_buckets():
    items: list[_Phrase] = []
    for tier, phrases in ((_T2, rp.T2_PHRASES), (_T1, rp.T1_PHRASES)):
        for ph in phrases:
            words = ph.lower().split()
            if len(words) < rp.MIN_PHRASE_WORDS:
                continue
            items.append(
                _Phrase(tier, [_stretch_pattern(w) for w in words], len(words), ph.lower())
            )
    buckets: dict[str, list[_Phrase]] = {}
    for it in items:
        buckets.setdefault(it.text[0], []).append(it)
    for lst in buckets.values():
        lst.sort(key=lambda p: (p.tier == _T2, p.nwords), reverse=True)
    return buckets


_PHRASE_BUCKETS = _build_phrase_buckets()

_Tok = namedtuple("_Tok", "folded start end")


@dataclass(frozen=True, slots=True)
class MuffleHit:
    word: str
    tier: str
    original: str
    masked: str
    kind: str = "word"  # "word" | "phrase"


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


def _classify_folded(folded: str) -> tuple[str | None, str | None]:
    if not folded or folded in _WHITELIST:
        return (None, None)
    first = folded[0]
    for tier, buckets in _BUCKETS:
        for word, rx in buckets.get(first, ()):
            if rx.fullmatch(folded):
                return (tier, word)
    return (None, None)


def _match_phrase(tokens, i: int):
    """Longest-/most-severe phrase starting at token i, or None."""
    folded = tokens[i].folded
    if not folded:
        return None
    for ph in _PHRASE_BUCKETS.get(folded[0], ()):
        if i + ph.nwords > len(tokens):
            continue
        if all(ph.regexes[j].fullmatch(tokens[i + j].folded) for j in range(ph.nwords)):
            return ph
    return None


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
        tokens = [
            _Tok(_fold_token(m.group(0)), m.start(), m.end())
            for m in _WORD_RE.finditer(text)
        ]
        hits: list[MuffleHit] = []
        out: list[str] = []
        last = 0
        i = 0
        while i < len(tokens):
            # Phrases first (longest / most-severe), consuming their tokens so a
            # word inside a matched phrase is not re-masked.
            ph = _match_phrase(tokens, i)
            if ph is not None:
                start, end = tokens[i].start, tokens[i + ph.nwords - 1].end
                original = text[start:end]
                masked = sparse_mask(original)
                hits.append(MuffleHit(ph.text, ph.tier, original, masked, "phrase"))
                out.append(text[last:start])
                out.append(masked)
                last = end
                i += ph.nwords
                continue

            tier, word = _classify_folded(tokens[i].folded)
            if tier in (_T1, _T2):
                start, end = tokens[i].start, tokens[i].end
                original = text[start:end]
                masked = sparse_mask(original)
                hits.append(MuffleHit(word, tier, original, masked, "word"))
                out.append(text[last:start])
                out.append(masked)
                last = end
            i += 1
        out.append(text[last:])
        return MuffleResult(masked_text="".join(out), hits=tuple(hits))
