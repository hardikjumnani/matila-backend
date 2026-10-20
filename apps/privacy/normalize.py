"""Shared text-normalisation for Veil (and later Muffle).

Produces the normalised *views* the scanner matches against. The ORIGINAL message
is never mutated; these are match-only representations. See docs/VEIL_V2_1_PLAN.md.

Views
-----
- ``fold_base``      NFKC + zero-width strip + cross-script confusables + lower +
                     single-space. The exact view used by the structured PII
                     regexes (email/URL/UPI/@handle) and self-name — unchanged
                     from v2, so structured detection has zero blast radius.
- ``fold_primary``   ``fold_base`` + particle de-glue + repeated-letter squeeze.
                     The keyword/meeting view (boundary-checked). Handles stretch
                     ("instaaa") and single-letter-doubling ("Mee"->"me") while
                     keeping word boundaries (low false-positive).
- ``collapse_all``   ``fold_primary`` with ALL separators removed — a continuous
                     string for substring matching of DISTINCTIVE needles only
                     (defeats word-gluing like "addmeoninstagram").
- ``prefold_numeric``digit view for the Number Reassembler (NFKC + Devanagari +
                     hex/oct/bin decode). NEVER squeezed (would corrupt numbers).
"""

from __future__ import annotations

import re
import unicodedata

from apps.privacy import ruleset

_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿­"), None)
_DEVANAGARI = str.maketrans("०१२३४५६७८९", "0123456789")
_BASE_RE = re.compile(r"0[xob][0-9a-f]+", re.IGNORECASE)
_WS_RE = re.compile(r"\s+")
_SQUEEZE_RE = re.compile(r"([a-z])\1+")            # runs of the SAME letter -> one
_NONALNUM_RE = re.compile(r"[^a-z0-9]+")

# Leading particles that are commonly glued to a following word. Kept small and
# conservative: each is split only when immediately followed by >=3 letters, and
# only particles that rarely begin a real needle are included (so "instagram" is
# never cut into "in stagram"). Postposition glue ("instape") is handled by the
# collapsed-view distinctive matcher instead.
_PARTICLES = ("the", "my", "on", "your", "ur")
_DEGLUE_RE = re.compile(
    r"\b(" + "|".join(_PARTICLES) + r")(?=[a-z]{3,})"
)


def deglue_particles(text: str) -> str:
    return _DEGLUE_RE.sub(r"\1 ", text)


def squeeze_letters(text: str) -> str:
    """Collapse a run of the same letter to a single one (digits untouched)."""
    return _SQUEEZE_RE.sub(r"\1", text)


def _decode_bases(text: str) -> str:
    def repl(m: re.Match) -> str:
        tok = m.group(0)
        base = {"x": 16, "o": 8, "b": 2}[tok[1].lower()]
        try:
            return str(int(tok[2:], base))
        except ValueError:
            return tok
    return _BASE_RE.sub(repl, text)


def fold_base(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "")
    t = t.translate(_ZERO_WIDTH)
    t = t.translate(ruleset.CONFUSABLES_TABLE)
    t = t.lower()
    return _WS_RE.sub(" ", t)


def fold_primary(text: str) -> str:
    """Keyword/meeting view: de-glue particles then squeeze repeated letters."""
    return squeeze_letters(deglue_particles(fold_base(text)))


def collapse_all(text: str) -> str:
    """Separator-free continuous view (for distinctive-needle substring match)."""
    return _NONALNUM_RE.sub("", fold_primary(text))


def prefold_numeric(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "")
    t = t.translate(_ZERO_WIDTH)
    t = t.translate(_DEVANAGARI)
    t = t.lower()
    return _decode_bases(t)


def digit_count(prefolded: str) -> int:
    return sum(ch.isdigit() for ch in prefolded)
