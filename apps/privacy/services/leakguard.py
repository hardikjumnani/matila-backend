"""LeakGuard — the deterministic scanner at the heart of the Veil engine.

Pure, dependency-light (no DB, no cache, no network): given a message string it
returns a :class:`Verdict`. Cross-message state (prior digit window + prior text
window) is owned by ``VeilService``, which passes it in.

Pipeline (docs/VEIL_V2_1_PLAN.md):
    normalise (views, once)  ->  detect (gated)  ->  score  ->  policy

Views (built once per scan in ``_Context``):
  - ``fold_base``    exact fold (NFKC + confusables + lower) — structured PII
                     regexes (email/URL/UPI/@handle) + self-name. Zero blast
                     radius vs v2.
  - ``fold_primary`` + de-glue + letter-squeeze — the boundary-checked keyword/
                     meeting view. Defeats stretch ("instaaa") and doubling
                     ("Mee"->"me") while keeping word boundaries (low FP).
  - ``collapsed``    separator-free view, matched only against DISTINCTIVE needles
                     (substring) and only when a glue signal is present. Defeats
                     word-gluing ("addmeoninstagram").

Efficiency: structured phone uses a fast ``[6-9]\\d{9}`` prefilter + the
reassembler; libphonenumber runs only when there are >=7 digits. The collapsed
automaton runs only when a long spaceless token is present. The cross-message
window dedupe runs only when the current message did not already block, and omits
libphonenumber (cross-message phones are covered by the digit reassembler).
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

import phonenumbers

from apps.privacy import dictionaries, fuzzy, normalize, ruleset
from apps.privacy.enums import LeakAction, LeakCategory, LeakSeverity

# Leet -> letters, for the keyword view only (never digits in the digit path).
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t",
                       "@": "a", "$": "s"})
_TOKEN_RE = re.compile(r"[a-z]+|\d+")

# Structured detector regexes (run on the exact fold_base view).
_PHONE_RE = re.compile(r"[6-9]\d{9}")
_PLAIN_EMAIL_RE = re.compile(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}")
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
_PLATFORMS = r"(?:" + "|".join(
    sorted(ruleset.PLATFORM_WORDS, key=len, reverse=True)
) + r")"
_HANDLE_AFTER_RE = re.compile(
    r"\b" + _PLATFORMS + r"\b\s*(?:is|id|handle|user(?:name)?|:|-|=|~)?\s*"
    r"@?([a-z0-9][a-z0-9_.]{2,})"
)

_HIGH = LeakSeverity.HIGH.value
_MEDIUM = LeakSeverity.MEDIUM.value
_LOW = LeakSeverity.LOW.value

_MEETING_SIGNALS = {"INVITE", "DESTINATION", "TIME", "DIRECTIONS", "LOCATION_PIN"}
_ASK_PLATFORM_DIST = 25
_STEER_PLATFORM_DIST = 20
_SELF_NAME_MIN_TOKEN = 3
_PHONE_MIN_DIGITS = 7      # libphonenumber only runs past this many digits
_GLUE_MIN_TOKEN = 6        # collapsed view only runs if a token is this long

_CATEGORY_PRIORITY = [
    LeakCategory.PHONE.value, LeakCategory.EMAIL.value, LeakCategory.UPI.value,
    LeakCategory.URL.value, LeakCategory.SOCIAL_HANDLE.value,
    LeakCategory.SELF_NAME.value, LeakCategory.MEETING.value,
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
    action: str
    hits: tuple[Hit, ...]
    digits: str
    combined_digits: str

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
        if any(h.severity == _MEDIUM for h in self.hits):
            return _MEDIUM
        return _LOW if self.hits else None

    @property
    def detectors(self) -> list[str]:
        return sorted({h.detector for h in self.hits})


@dataclass(frozen=True, slots=True)
class _Context:
    raw: str
    fold_base: str
    fold_primary: str
    prefolded: str
    digits: str
    combined_digits: str
    tally_digits: str
    sender_name: str


def extract_digits(text: str) -> str:
    """Strip prose; concatenate every number-bearing token (literal, spelled-out
    EN/Indian-language, decoded hex/oct/bin, Devanagari) with double/triple
    expansion. The Number Reassembler's front end. Digits are never squeezed."""
    folded = normalize.prefold_numeric(text)
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
        elif tok in dictionaries.SPELLED_DIGITS:
            out.append(dictionaries.SPELLED_DIGITS[tok] * repeat)
            repeat = 1
        else:
            repeat = 1
    return "".join(out)


def looks_like_phone(digits: str) -> bool:
    return bool(_PHONE_RE.search(digits))


# -- tally / run-length digit decoding ----------------------------------------
# Evasion: encode a phone number with NO literal digits, as counts of a repeated
# token ("N dots = digit N", space-separated), as repeated letters/emoji, or as
# Morse. The decoders below only PROPOSE a digit string; the phone validator
# (_PHONE_RE) is the sole gate, so a non-phone decode never blocks. Zero-FP by
# construction: a hit needs a long contiguous block of non-prose tokens
# (repeated-char runs or Morse codes) whose lengths/codes spell a valid mobile.
_TALLY_MIN_GROUPS = 7   # consider a block only once this many pure groups line up
_TALLY_MAX_RUN = 12     # a longer run is a divider/emphasis, not a digit tally
_MORSE_DIGITS = {
    "-----": "0", ".----": "1", "..---": "2", "...--": "3", "....-": "4",
    ".....": "5", "-....": "6", "--...": "7", "---..": "8", "----.": "9",
}


def _runlength_digits(tokens: list[str]) -> str:
    """Longest contiguous block of pure single-character tokens (dots, dashes,
    letters, single-codepoint emoji), each decoded as (run length % 10) so a 10
    run encodes 0. Empty unless a block reaches ``_TALLY_MIN_GROUPS``. Prose
    breaks the block (a normal word is not a single repeated character)."""
    best: list[int] = []
    cur: list[int] = []
    for tok in tokens:
        if 1 <= len(tok) <= _TALLY_MAX_RUN and not tok.isdigit() and len(set(tok)) == 1:
            cur.append(len(tok))
        else:
            if len(cur) > len(best):
                best = cur
            cur = []
    if len(cur) > len(best):
        best = cur
    if len(best) >= _TALLY_MIN_GROUPS:
        return "".join(str(n % 10) for n in best)
    return ""


def _morse_digits(tokens: list[str]) -> str:
    """Longest contiguous block of Morse digit codes (five dot/dash symbols each),
    e.g. ``--... ...-- .....`` -> ``735``. Empty below ``_TALLY_MIN_GROUPS``."""
    best: list[str] = []
    cur: list[str] = []
    for tok in tokens:
        decoded = _MORSE_DIGITS.get(tok)
        if decoded is not None:
            cur.append(decoded)
        else:
            if len(cur) > len(best):
                best = cur
            cur = []
    if len(cur) > len(best):
        best = cur
    if len(best) >= _TALLY_MIN_GROUPS:
        return "".join(best)
    return ""


def decode_tally_digits(text: str) -> str:
    """Candidate phone digits recovered from a tally/run-length or Morse encoding
    (evasions that carry no literal digits). Returns a digit string ONLY when it
    forms a valid mobile (``_PHONE_RE``); a non-phone decode yields '' and never
    blocks. This single phone gate is what keeps the decoders zero false-positive."""
    tokens = (text or "").split()
    if len(tokens) < _TALLY_MIN_GROUPS:
        return ""
    for candidate in (_runlength_digits(tokens), _morse_digits(tokens)):
        if candidate and _PHONE_RE.search(candidate):
            return candidate
    return ""


def _near(a: list[int], b: list[int], max_dist: int) -> bool:
    return any(abs(x - y) <= max_dist for x in a for y in b)


class LeakGuard:
    """Deterministic contact/PII/meeting leakage scanner."""

    def scan(
        self,
        text: str,
        *,
        prior_digits: str = "",
        prior_text: str = "",
        sender_name: str = "",
    ) -> Verdict:
        raw = text or ""
        digits = extract_digits(raw)
        combined = (prior_digits or "") + digits
        ctx = _Context(
            raw=raw,
            fold_base=normalize.fold_base(raw),
            fold_primary=normalize.fold_primary(raw),
            prefolded=normalize.prefold_numeric(raw),
            digits=digits,
            combined_digits=combined,
            tally_digits=decode_tally_digits(raw),
            sender_name=sender_name or "",
        )
        hits = self._detect(ctx, include_phone=True)
        blocked_now = any(h.severity in (_HIGH, _MEDIUM) for h in hits)

        # Cross-message completion: only when this message did not already block,
        # and using the lighter category-only path (no libphonenumber).
        if prior_text and not blocked_now:
            window_cats = self._block_categories(prior_text + " " + raw, sender_name)
            prior_cats = self._block_categories(prior_text, sender_name)
            for cat in window_cats - prior_cats:
                hits.append(Hit(cat, _HIGH, "window", "<cross-message>"))

        action = (
            LeakAction.BLOCK.value
            if any(h.severity in (_HIGH, _MEDIUM) for h in hits)
            else LeakAction.ALLOW.value
        )
        return Verdict(
            action=action, hits=tuple(hits), digits=digits, combined_digits=combined
        )

    # -- single-message detection ------------------------------------------
    def _detect(self, ctx: _Context, *, include_phone: bool) -> list[Hit]:
        hits: list[Hit] = []

        if include_phone:
            phone = self._phone(ctx)
            if phone is not None:
                hits.append(phone)

        fb = ctx.fold_base
        em = _PLAIN_EMAIL_RE.search(fb) or _VERBOSE_EMAIL_RE.search(fb)
        if em:
            hits.append(Hit(LeakCategory.EMAIL.value, _HIGH, "email", em.group(0)))
        um = _UPI_RE.search(fb)
        if um:
            hits.append(Hit(LeakCategory.UPI.value, _HIGH, "upi", um.group(0)))
        urlm = _URL_RE.search(fb)
        if urlm:
            hits.append(Hit(LeakCategory.URL.value, _HIGH, "url", urlm.group(0)))

        hm = _HANDLE_RE.search(fb)
        if hm and not em:
            hits.append(
                Hit(LeakCategory.SOCIAL_HANDLE.value, _HIGH, "at_handle", hm.group(0))
            )
        if not em:
            handle = self._platform_handle(fb)
            if handle is not None:
                hits.append(handle)

        hits.extend(self._signal_scan(ctx, suppress_platform=bool(hits)))

        if ctx.sender_name:
            sn = self._self_name(fb, ctx.sender_name)
            if sn is not None:
                hits.append(sn)
        return hits

    def _block_categories(self, text: str, sender_name: str) -> set[str]:
        """Blocking categories for a (multi-message) chunk — cross-message dedupe
        only. Omits libphonenumber (the digit reassembler covers cross-message
        phones via combined_digits)."""
        raw = text or ""
        ctx = _Context(
            raw=raw,
            fold_base=normalize.fold_base(raw),
            fold_primary=normalize.fold_primary(raw),
            prefolded=normalize.prefold_numeric(raw),
            digits=extract_digits(raw),
            combined_digits=extract_digits(raw),
            tally_digits=decode_tally_digits(raw),
            sender_name=sender_name or "",
        )
        hits = self._detect(ctx, include_phone=True)
        return {h.category for h in hits if h.severity in (_HIGH, _MEDIUM)}

    # -- phone -------------------------------------------------------------
    def _phone(self, ctx: _Context) -> Hit | None:
        if _PHONE_RE.search(ctx.digits):
            return Hit(LeakCategory.PHONE.value, _HIGH, "phone",
                       _PHONE_RE.search(ctx.digits).group(0))
        # Tally / run-length / Morse encodings (decode_tally_digits only returns a
        # string that already validates as a mobile, so presence => a phone leak).
        if ctx.tally_digits:
            return Hit(LeakCategory.PHONE.value, _HIGH, "tally",
                       _PHONE_RE.search(ctx.tally_digits).group(0))
        if _PHONE_RE.search(ctx.combined_digits):
            return Hit(LeakCategory.PHONE.value, _HIGH, "reassembler", "<reassembled>")
        if normalize.digit_count(ctx.prefolded) >= _PHONE_MIN_DIGITS \
                and self._phonenumbers_hit(ctx.prefolded):
            return Hit(LeakCategory.PHONE.value, _HIGH, "libphonenumber", "<intl>")
        return None

    @staticmethod
    def _phonenumbers_hit(prefolded: str) -> bool:
        try:
            for match in phonenumbers.PhoneNumberMatcher(prefolded, "IN"):
                if phonenumbers.is_valid_number(match.number):
                    return True
        except Exception:  # noqa: BLE001 — never let the parser break scanning.
            return False
        return False

    # -- keyword / meeting signals -----------------------------------------
    def _signal_scan(self, ctx: _Context, *, suppress_platform: bool) -> list[Hit]:
        # Primary (boundary-checked) view, plus its leet twin (positions align).
        prim_pos: dict[str, list[int]] = defaultdict(list)
        fp = ctx.fold_primary
        for view in (fp, fp.translate(_LEET)):
            for start, _end, signals in dictionaries.scan_primary(view):
                for sig in signals:
                    prim_pos[sig].append(start)
        present = {s for s, p in prim_pos.items() if p}

        # Presence-only signals from the glued view (collapsed, gated) and the
        # fuzzy view (edit-distance 1 over distinctive needles). These have no
        # positions, so they only ever contribute to the COMBINATION rules below,
        # never a standalone proximity block.
        extra: set[str] = set()
        if self._has_glue(fp):
            collapsed = normalize.collapse_all(ctx.raw)
            for view in (collapsed, collapsed.translate(_LEET)):
                for _s, _e, signals in dictionaries.scan_collapsed(view):
                    extra |= set(signals)
        extra |= fuzzy.fuzzy_signals(fp)
        any_present = present | extra

        hits: list[Hit] = []
        # Exact ask/steer use PROXIMITY (FP-safe); glued/fuzzy use PRESENCE but
        # still require a platform to be present somewhere.
        solicit = _near(prim_pos["ASK"], prim_pos["PLATFORM"], _ASK_PLATFORM_DIST) or (
            "ASK" in extra and "PLATFORM" in any_present
        )
        if solicit:
            hits.append(Hit(LeakCategory.SOLICITATION.value, _HIGH, "solicitation", "<ask>"))

        steer = _near(prim_pos["STEER"], prim_pos["PLATFORM"], _STEER_PLATFORM_DIST) or (
            "STEER" in extra and "PLATFORM" in any_present
        )
        if steer:
            hits.append(Hit(LeakCategory.STEERING.value, _HIGH, "steering", "<steer>"))

        meet = {s for s in _MEETING_SIGNALS if s in any_present}
        if self._meeting_blocks(meet):
            hits.append(
                Hit(LeakCategory.MEETING.value, _HIGH, "meeting", "+".join(sorted(meet)))
            )

        if not hits and not suppress_platform and "PLATFORM" in any_present:
            hits.append(Hit(LeakCategory.PLATFORM.value, _LOW, "platform_mention", "<platform>"))
        return hits

    @staticmethod
    def _has_glue(fold_primary: str) -> bool:
        return any(len(tok) >= _GLUE_MIN_TOKEN for tok in fold_primary.split())

    @staticmethod
    def _meeting_blocks(present: set[str]) -> bool:
        if "LOCATION_PIN" in present:
            return True
        if "INVITE" in present and present & {"DESTINATION", "TIME", "DIRECTIONS"}:
            return True
        if "DIRECTIONS" in present and "DESTINATION" in present:
            return True
        return False

    @staticmethod
    def _platform_handle(fold_base: str) -> Hit | None:
        for source in (fold_base, fold_base.translate(_LEET)):
            for m in _HANDLE_AFTER_RE.finditer(source):
                val = m.group(1)
                if any(c.isdigit() for c in val) or "_" in val or "." in val:
                    return Hit(
                        LeakCategory.SOCIAL_HANDLE.value, _HIGH,
                        "platform_handle", m.group(0),
                    )
        return None

    @staticmethod
    def _self_name(fold_base: str, sender_name: str) -> Hit | None:
        tokens = {
            t for t in re.split(r"[^a-z0-9]+", (sender_name or "").lower())
            if len(t) >= _SELF_NAME_MIN_TOKEN
        }
        for tok in tokens:
            if re.search(r"(?<![a-z])" + re.escape(tok) + r"(?![a-z])", fold_base):
                return Hit(LeakCategory.SELF_NAME.value, _HIGH, "self_name", tok)
        return None
