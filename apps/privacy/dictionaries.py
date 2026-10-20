"""Dictionary loader + compiled matchers for Veil.

Builds TWO Aho-Corasick automatons once at startup (immutable, shared read-only):

- ``AUTOMATON_PRIMARY``  — every needle under ``normalize.fold_primary``; matched
  word-boundary-checked. Catches normal text, stretch, de-glued particles and
  single-letter-doubling misspellings, all with low false positives.
- ``AUTOMATON_COLLAPSED`` — only DISTINCTIVE needles (phrases, and single words
  >= ``DISTINCTIVE_MIN_LEN``) under ``normalize.collapse_all``; matched as a
  substring (no boundary). Defeats word-gluing ("addmeoninstagram") without the
  Scunthorpe explosion a full no-boundary match would cause.

Matching is one O(message length) pass per automaton, independent of dictionary
size, so the 10-language coverage costs startup memory, not per-message latency.
"""

from __future__ import annotations

import ahocorasick

from apps.privacy import normalize, ruleset
from apps.privacy.languages import LANGUAGES

# Language dictionary key -> signal name emitted to the scanner.
_KEYWORD_CATEGORIES: dict[str, str] = {
    "ask_verbs": "ASK",
    "steer_verbs": "STEER",
    "invite_words": "INVITE",
    "destination_words": "DESTINATION",
    "time_words": "TIME",
    "direction_words": "DIRECTIONS",
    "location_pin": "LOCATION_PIN",
}

# A single word is "distinctive" enough for separator-free substring matching
# only at this length; shorter ones (insta, gmail, cafe, add) match
# boundary-checked only, so "instance"/"install" never trip the collapsed view.
# Multi-word phrases are always distinctive (their collapsed form is specific).
DISTINCTIVE_MIN_LEN = 7


def _raw_signals_by_needle() -> dict[str, set[str]]:
    signals: dict[str, set[str]] = {}
    for cats in LANGUAGES.values():
        for key, signal in _KEYWORD_CATEGORIES.items():
            for word in cats.get(key, []):
                needle = (word or "").lower().strip()
                if needle:
                    signals.setdefault(needle, set()).add(signal)
    for word in ruleset.PLATFORM_WORDS:
        needle = (word or "").lower().strip()
        if needle:
            signals.setdefault(needle, set()).add("PLATFORM")
    return signals


def _is_distinctive(needle: str) -> bool:
    return " " in needle or len(needle) >= DISTINCTIVE_MIN_LEN


def _build_automaton(transform) -> ahocorasick.Automaton:
    """One automaton keyed by ``transform(needle)``; payload merges signals of
    every raw needle that maps to the same key. ``transform`` returning '' skips
    the needle (and ``_distinctive_only`` is applied by the caller)."""
    merged: dict[str, set[str]] = {}
    for needle, signals in _raw_signals_by_needle().items():
        if transform is _COLLAPSED and not _is_distinctive(needle):
            continue
        key = transform(needle)
        if key:
            merged.setdefault(key, set()).update(signals)
    automaton = ahocorasick.Automaton()
    for key, signals in merged.items():
        automaton.add_word(key, (key, frozenset(signals)))
    automaton.make_automaton()
    return automaton


_PRIMARY = normalize.fold_primary
_COLLAPSED = normalize.collapse_all

AUTOMATON_PRIMARY = _build_automaton(_PRIMARY)
AUTOMATON_COLLAPSED = _build_automaton(_COLLAPSED)


def _merge_spelled_digits() -> dict[str, str]:
    merged: dict[str, str] = {}
    for cats in LANGUAGES.values():
        merged.update(cats.get("spelled_digits", {}))
    return merged


SPELLED_DIGITS = _merge_spelled_digits()


def _is_boundary(ch: str) -> bool:
    return not ch.isalnum()


def scan_primary(folded_primary: str) -> list[tuple[int, int, frozenset[str]]]:
    """Whole-word/phrase dictionary hits (boundary-checked, Scunthorpe-safe)."""
    if not folded_primary:
        return []
    n = len(folded_primary)
    out: list[tuple[int, int, frozenset[str]]] = []
    for end, (key, signals) in AUTOMATON_PRIMARY.iter(folded_primary):
        start = end - len(key) + 1
        before = start == 0 or _is_boundary(folded_primary[start - 1])
        after = end == n - 1 or _is_boundary(folded_primary[end + 1])
        if before and after:
            out.append((start, end, signals))
    return out


def scan_collapsed(collapsed: str) -> list[tuple[int, int, frozenset[str]]]:
    """Distinctive-needle hits in the separator-free view (substring, no
    boundary check — the view has no boundaries)."""
    if not collapsed:
        return []
    return [
        (end - len(key) + 1, end, signals)
        for end, (key, signals) in AUTOMATON_COLLAPSED.iter(collapsed)
    ]
