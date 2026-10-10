"""LeakGuard — the deterministic scanner at the heart of the Veil engine.

Pure, dependency-free (no DB, no cache, no network): given a message string it
returns a :class:`Verdict`. All cross-message state (the rolling digit window)
is owned by ``VeilService``, which passes ``prior_digits`` in.

Pipeline (see docs/VEIL_ENGINE_PLAN.md):
    normalise  ->  detect  ->  score  ->  policy

The hard part is *normalisation* (defeating evasion), not the patterns:
  - Unicode NFKC + zero-width strip + Devanagari digits,
  - leet-folding for keyword matching,
  - "at the rate"/"dot" -> @/. for verbose emails,
  - spelled-out digits (EN + Hinglish) and "double/triple" expansion,
  - hex/octal/binary decoding (0x / 0o / 0b),
  - a Number Reassembler that strips prose and concatenates every number-bearing
    token (literal, spelled, decoded) to catch a phone number smuggled across
    words and/or messages.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from apps.privacy.enums import LeakAction, LeakCategory, LeakSeverity
from apps.privacy import ruleset

# ---------------------------------------------------------------------------
# Normalisation tables
# ---------------------------------------------------------------------------
_ZERO_WIDTH = dict.fromkeys(
    map(ord, "​‌‍⁠﻿­"), None
)
_DEVANAGARI = str.maketrans("०१२३४५६७८९", "0123456789")
# Leet -> letters, used ONLY for keyword matching (never for digit extraction).
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t",
                       "@": "a", "$": "s"})

_BASE_RE = re.compile(r"0[xob][0-9a-f]+", re.IGNORECASE)
_TOKEN_RE = re.compile(r"[a-z]+|\d+")

# ---------------------------------------------------------------------------
# Detector regexes (compiled once)
# ---------------------------------------------------------------------------
# A 10-digit Indian mobile run (6-9 lead) appearing anywhere in a digit string.
_PHONE_RE = re.compile(r"[6-9]\d{9}")

_PLAIN_EMAIL_RE = re.compile(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}")
# "foo at gmail dot com" and bracketed variants.
_VERBOSE_EMAIL_RE = re.compile(
    r"[a-z0-9._%+-]+\s*(?:@|\(at\)|\[at\]|\bat the rate\b|\bat\b)\s*"
    r"[a-z0-9.-]+\s*(?:\.|\(dot\)|\bdot\b)\s*[a-z]{2,}"
)
_UPI_RE = re.compile(
    r"\b[a-z0-9.\-]{2,}@(?:" + "|".join(map(re.escape, ruleset.PSP_HANDLES)) + r")\b"
)
_URL_RE = re.compile(
    r"(?:https?://|www\.)\S+"
    r"|\b[a-z0-9][a-z0-9-]*\.(?:" + "|".join(ruleset.URL_TLDS) + r")\b(?:/\S*)?"
)
_HANDLE_RE = re.compile(r"(?<![a-z0-9._@])@[a-z0-9._]{2,}")

_PLATFORMS = r"(?:" + "|".join(sorted(ruleset.PLATFORM_WORDS, key=len, reverse=True)) + r")"
_ASK = r"(?:" + "|".join(re.escape(v) for v in ruleset.ASK_VERBS) + r")"
_STEER = r"(?:" + "|".join(re.escape(v) for v in ruleset.STEER_VERBS) + r")"

_ASK_RE = re.compile(r"\b" + _ASK + r"\b.{0,25}?\b" + _PLATFORMS + r"\b")
# Hinglish "number de / number do / insta bhej".
_DE_RE = re.compile(r"\b" + _PLATFORMS + r"\b\s+(?:de|do|dedo|bhej|bhejo|bata)\b")
_STEER_RE = re.compile(r"\b" + _STEER + r"\b.{0,15}?\b" + _PLATFORMS + r"\b")
_MEET_RE = re.compile(
    r"\b(?:let'?s|lets|wanna|shall we|we can|can we)\b.{0,12}\bmeet\b"
    r"|\bmeet\s+(?:up|me|outside|irl|in person)\b"
)
_PLATFORM_PRESENT_RE = re.compile(r"\b" + _PLATFORMS + r"\b")
# platform followed (within a few chars) by a handle-ish value.
_HANDLE_AFTER_RE = re.compile(
    r"\b" + _PLATFORMS + r"\b\s*(?:is|id|handle|user(?:name)?|:|-|=|~)?\s*"
    r"@?([a-z0-9][a-z0-9_.]{2,})"
)

_HIGH = LeakSeverity.HIGH.value
_LOW = LeakSeverity.LOW.value

# Category priority (most -> least severe) for choosing the "top" hit.
_CATEGORY_PRIORITY = [
    LeakCategory.PHONE.value, LeakCategory.EMAIL.value, LeakCategory.UPI.value,
    LeakCategory.URL.value, LeakCategory.SOCIAL_HANDLE.value,
    LeakCategory.SOLICITATION.value, LeakCategory.STEERING.value,
    LeakCategory.PLATFORM.value,
]


@dataclass(frozen=True, slots=True)
class Hit:
    category: str
    severity: str
    detector: str
    span: str


@dataclass(frozen=True, slots=True)
class Verdict:
    action: str                       # ALLOW | BLOCK (ESCALATE is decided by VeilService)
    hits: tuple[Hit, ...]
    digits: str                       # digits extracted from THIS message
    combined_digits: str              # prior_digits + this message's digits

    @property
    def blocked(self) -> bool:
        return self.action != LeakAction.ALLOW.value

    @property
    def top_category(self) -> str | None:
        present = {h.category for h in self.hits}
        for c in _CATEGORY_PRIORITY:
            if c in present:
                return c
        return None

    @property
    def top_severity(self) -> str | None:
        if any(h.severity == _HIGH for h in self.hits):
            return _HIGH
        if any(h.severity == LeakSeverity.MEDIUM.value for h in self.hits):
            return LeakSeverity.MEDIUM.value
        return _LOW if self.hits else None

    @property
    def detectors(self) -> list[str]:
        return sorted({h.detector for h in self.hits})


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------
def _decode_bases(text: str) -> str:
    """Replace 0x../0o../0b.. tokens with their decimal expansion."""
    def repl(m: re.Match) -> str:
        tok = m.group(0)
        base = {"x": 16, "o": 8, "b": 2}[tok[1].lower()]
        try:
            return str(int(tok[2:], base))
        except ValueError:
            return tok
    return _BASE_RE.sub(repl, text)


def _prefold_numeric(text: str) -> str:
    t = unicodedata.normalize("NFKC", text)
    t = t.translate(_ZERO_WIDTH)
    t = t.translate(_DEVANAGARI)
    t = t.lower()
    return _decode_bases(t)


def _fold(text: str) -> str:
    t = unicodedata.normalize("NFKC", text)
    t = t.translate(_ZERO_WIDTH)
    t = t.lower()
    return re.sub(r"\s+", " ", t)


def extract_digits(text: str) -> str:
    """Strip prose; concatenate every number-bearing token (literal digits,
    spelled-out EN/Hinglish, decoded hex/oct/bin, Devanagari) in order, with
    'double/triple' expansion. This is the Number Reassembler's front end."""
    folded = _prefold_numeric(text)
    out: list[str] = []
    repeat = 1
    for tok in _TOKEN_RE.findall(folded):
        if tok == "double":
            repeat = 2
            continue
        if tok == "triple":
            repeat = 3
            continue
        if tok.isdigit():
            out.append(tok * repeat if (repeat > 1 and len(tok) == 1) else tok)
            repeat = 1
        elif tok in ruleset.SPELLED_DIGITS:
            out.append(ruleset.SPELLED_DIGITS[tok] * repeat)
            repeat = 1
        else:
            repeat = 1
    return "".join(out)


def looks_like_phone(digits: str) -> bool:
    return bool(_PHONE_RE.search(digits))


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------
class LeakGuard:
    """Deterministic contact/PII leakage scanner."""

    def scan(self, text: str, *, prior_digits: str = "") -> Verdict:
        raw = text or ""
        folded = _fold(raw)
        leet = folded.translate(_LEET)
        digits = extract_digits(raw)
        combined = (prior_digits or "") + digits

        hits: list[Hit] = []

        # --- Phone (this message, else reassembled across the window) --------
        m = _PHONE_RE.search(digits)
        if m:
            hits.append(Hit(LeakCategory.PHONE.value, _HIGH, "phone", m.group(0)))
        elif _PHONE_RE.search(combined):
            hits.append(
                Hit(LeakCategory.PHONE.value, _HIGH, "reassembler", "<reassembled>")
            )

        # --- Email / UPI / URL ---------------------------------------------
        em = _PLAIN_EMAIL_RE.search(folded) or _VERBOSE_EMAIL_RE.search(folded)
        if em:
            hits.append(Hit(LeakCategory.EMAIL.value, _HIGH, "email", em.group(0)))
        um = _UPI_RE.search(folded)
        if um:
            hits.append(Hit(LeakCategory.UPI.value, _HIGH, "upi", um.group(0)))
        urlm = _URL_RE.search(folded)
        if urlm:
            hits.append(Hit(LeakCategory.URL.value, _HIGH, "url", urlm.group(0)))

        # --- Explicit @handle ----------------------------------------------
        hm = _HANDLE_RE.search(folded)
        if hm and not em:  # an email also matches '@...'; don't double-count
            hits.append(
                Hit(LeakCategory.SOCIAL_HANDLE.value, _HIGH, "at_handle", hm.group(0))
            )

        # --- Keyword-driven: solicitation / steering / platform+handle ------
        hits.extend(self._keyword_scan(folded, leet))

        action = (
            LeakAction.BLOCK.value
            if any(h.severity in (_HIGH, LeakSeverity.MEDIUM.value) for h in hits)
            else LeakAction.ALLOW.value
        )
        return Verdict(
            action=action, hits=tuple(hits), digits=digits, combined_digits=combined
        )

    def _keyword_scan(self, folded: str, leet: str) -> list[Hit]:
        hits: list[Hit] = []

        sm = _ASK_RE.search(leet) or _DE_RE.search(leet)
        if sm:
            hits.append(
                Hit(LeakCategory.SOLICITATION.value, _HIGH, "solicitation", sm.group(0))
            )

        stm = _STEER_RE.search(leet) or _MEET_RE.search(leet)
        if stm:
            hits.append(
                Hit(LeakCategory.STEERING.value, _HIGH, "steering", stm.group(0))
            )

        # platform followed by a handle-ish value (must contain a digit / _ / .).
        # Check the plain view (digits intact) then the leet view (catches a
        # leet-obfuscated platform like "1nsta cool_guy").
        handle_found = False
        for source in (folded, leet):
            for m in _HANDLE_AFTER_RE.finditer(source):
                val = m.group(1)
                if any(c.isdigit() for c in val) or "_" in val or "." in val:
                    hits.append(
                        Hit(LeakCategory.SOCIAL_HANDLE.value, _HIGH,
                            "platform_handle", m.group(0))
                    )
                    handle_found = True
                    break
            if handle_found:
                break

        # lone platform mention with nothing else -> LOW (allowed, but recorded)
        if not hits and _PLATFORM_PRESENT_RE.search(leet):
            hits.append(
                Hit(LeakCategory.PLATFORM.value, _LOW, "platform_mention",
                    _PLATFORM_PRESENT_RE.search(leet).group(0))
            )
        return hits
