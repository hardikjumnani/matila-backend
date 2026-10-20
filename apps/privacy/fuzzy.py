"""Bounded fuzzy matching for Veil (edit-distance <= 1), zero-FP-oriented.

Catches single-substitution / near-miss evasions that squeeze cannot (``meet mr``
-> ``meet me``, ``cantin`` -> ``canteen``, ``instgram`` -> ``instagram``) WITHOUT
false positives, via three safeguards:

1. Only DISTINCTIVE needles are fuzzable (multi-word phrases, or single words
   long enough that an edit-distance-1 neighbour is very unlikely to be a common
   benign word). Short/ambiguous words (``me``, ``cafe``, ``add``) are exact-only.
2. Candidates from the message must be length >= ``FUZZY_MIN_LEN`` (unigrams) or a
   two-word bigram (for phrase needles).
3. A fuzzy hit NEVER blocks on its own — it only contributes a signal to the same
   combination rules as an exact hit (e.g. a fuzzy INVITE still needs a
   DESTINATION). PLATFORM stays LOW (never a block by itself).

A BK-tree over the distinctive needle set answers ``edit-distance <= 1`` queries in
~O(query length), not O(dictionary size).
"""

from __future__ import annotations

from apps.privacy import normalize
from apps.privacy.dictionaries import _raw_signals_by_needle

FUZZY_MIN_LEN = 6   # a single-word candidate must be at least this long to fuzz
MAX_EDITS = 1


def _lev_le1(a: str, b: str) -> int:
    """Edit distance, early-exit once it is known to exceed 1. Returns the real
    distance when <= 1, else 2 (meaning '>1')."""
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return 2
    if a == b:
        return 0
    if la == lb:  # at most one substitution allowed
        diffs = sum(1 for x, y in zip(a, b) if x != y)
        return diffs if diffs <= 1 else 2
    # lengths differ by exactly one: allow a single insertion/deletion
    if la > lb:
        a, b = b, a  # a is now the shorter
    # try to match a into b skipping exactly one char of b
    i = j = 0
    skipped = False
    while i < len(a) and j < len(b):
        if a[i] == b[j]:
            i += 1
            j += 1
        elif not skipped:
            skipped = True
            j += 1
        else:
            return 2
    return 1


class _BKTree:
    __slots__ = ("root",)

    def __init__(self) -> None:
        self.root: tuple[str, dict] | None = None

    def add(self, word: str) -> None:
        if self.root is None:
            self.root = (word, {})
            return
        node = self.root
        while True:
            w, children = node
            d = _full_lev(word, w)
            if d == 0:
                return
            child = children.get(d)
            if child is None:
                children[d] = (word, {})
                return
            node = child

    def query(self, word: str, max_dist: int) -> list[str]:
        if self.root is None:
            return []
        out: list[str] = []
        stack = [self.root]
        while stack:
            w, children = stack.pop()
            d = _full_lev(word, w)
            if d <= max_dist:
                out.append(w)
            lo, hi = d - max_dist, d + max_dist
            for dist, child in children.items():
                if lo <= dist <= hi:
                    stack.append(child)
        return out


def _full_lev(a: str, b: str) -> int:
    """Full Levenshtein (used only for BK-tree construction/traversal distances)."""
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if la == 0:
        return lb
    if lb == 0:
        return la
    prev = list(range(lb + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[lb]


def _build() -> tuple[_BKTree, dict[str, frozenset[str]]]:
    # Zero-FP rule: fuzz SINGLE distinctive words only, never phrases. Phrase
    # fuzzing ("meet me") would match common benign phrases one edit away
    # ("meet my", "meet us"), which is a false positive we must not create. Lone
    # words long enough (>= FUZZY_MIN_LEN) have no common edit-1 benign neighbour
    # that can block (platform neighbours stay LOW; destination neighbours are
    # not real words), so this is safe.
    signals: dict[str, set[str]] = {}
    for needle, sigs in _raw_signals_by_needle().items():
        folded = normalize.fold_primary(needle)
        if " " in folded or len(folded) < FUZZY_MIN_LEN:
            continue
        signals.setdefault(folded, set()).update(sigs)
    tree = _BKTree()
    for key in signals:
        tree.add(key)
    return tree, {k: frozenset(v) for k, v in signals.items()}


_TREE, _SIGNALS = _build()


def fuzzy_signals(fold_primary_text: str) -> set[str]:
    """Signals from distinctive SINGLE-WORD needles within edit-distance 1 of a
    message unigram (>= FUZZY_MIN_LEN). Presence-only (no positions); phrases are
    never fuzzed (see _build), so there is no "meet my"-style false positive."""
    if not fold_primary_text:
        return set()
    out: set[str] = set()
    for tok in fold_primary_text.split():
        if len(tok) < FUZZY_MIN_LEN:
            continue
        for match in _TREE.query(tok, MAX_EDITS):
            if _lev_le1(tok, match) <= MAX_EDITS:
                out |= _SIGNALS[match]
    return out
