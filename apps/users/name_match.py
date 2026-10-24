"""Name normalization + matching for the per-user block list.

Pure string logic (no DB): used both when storing a blocked name (normalize) and
at matchmaking time (compare a user's blocked entries against a candidate's name).
Token-based and accent/case-insensitive, so "Himanshu" blocks any name containing
that token and "José" blocks "Jose". It is deliberately name-string only - never a
user lookup - so it cannot reveal whether a name is on the app.
"""

from __future__ import annotations

import re
import unicodedata

_WS = re.compile(r"\s+")
_NONALNUM = re.compile(r"[^a-z0-9]+")


def normalize_name(s: str) -> str:
    """Lowercase, strip accents (café -> cafe), collapse whitespace, trim."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return _WS.sub(" ", s.lower()).strip()


def name_tokens(s: str) -> set[str]:
    """Normalized name split into word tokens (on any non-alphanumeric)."""
    return {t for t in _NONALNUM.split(normalize_name(s)) if t}


def name_is_blocked(blocked_entries, target_full_name: str) -> bool:
    """True if any blocked entry matches the target's name.

    An entry matches when ALL of its tokens appear in the target's name tokens:
    "himanshu" matches "Himanshu Chauhan"; "himanshu chauhan" matches only a name
    with both tokens. Token equality (not substring), so "himanshu" never matches
    "himanshuda". ``blocked_entries`` is an iterable of (already-normalized) strings.
    """
    target = name_tokens(target_full_name)
    if not target:
        return False
    for entry in blocked_entries:
        toks = name_tokens(entry)
        if toks and toks <= target:
            return True
    return False
