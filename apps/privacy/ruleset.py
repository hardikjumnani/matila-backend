"""Veil ruleset — the versioned data the scanner is built from.

This is the single source of truth for the word-lists and tone templates. The
scanner (``LeakGuard``) compiles its regexes from these lists, and ``export()``
serialises them for the (future) client ruleset endpoint so the frontend
pre-send check can mirror the backend without a code release.

Deterministic only — no AI. Everything here is tunable; bump ``RULESET_VERSION``
whenever the lists change so ``LeakEvent.rule_version`` stays meaningful.
"""

from __future__ import annotations

RULESET_VERSION = "2026.10.10-v1"

# --- Spelled-out digits -----------------------------------------------------
# English + a conservative Hinglish set. Deliberately EXCLUDES ambiguous tokens
# that collide with ordinary English words ("do", "no", "oh" alone, "to") to
# keep the Number Reassembler's false-positive rate low. Devanagari digits are
# handled by a direct translation table in the scanner.
SPELLED_DIGITS: dict[str, str] = {
    "zero": "0", "oh": "0", "nought": "0", "shunya": "0",
    "one": "1", "ek": "1",
    "two": "2", "dho": "2",
    "three": "3", "teen": "3",
    "four": "4", "char": "4",
    "five": "5", "paanch": "5", "panch": "5",
    "six": "6", "chhe": "6", "che": "6", "chah": "6",
    "seven": "7", "saat": "7", "sat": "7",
    "eight": "8", "aath": "8", "ath": "8",
    "nine": "9", "nau": "9",
}

# --- Platforms / contact nouns (for steering / solicitation / handles) ------
PLATFORM_WORDS: list[str] = [
    "instagram", "insta", "instagrm", "ig", "gram",
    "snapchat", "snap", "sc",
    "whatsapp", "whatsap", "watsapp", "whatzapp", "wsp", "wa",
    "telegram", "tele", "tgram", "tg",
    "discord", "disc",
    "signal", "messenger", "facebook", "fb", "twitter", "reddit", "linkedin",
    "gpay", "googlepay", "phonepe", "paytm", "bhim", "upi",
    "email", "gmail", "mail",
    "number", "mobile", "contact", "digits", "phone", "cell", "whatsap",
]

# UPI PSP handles (the part after '@' in a VPA). Restricted list keeps the UPI
# detector from firing on ordinary "name@word" text.
PSP_HANDLES: list[str] = [
    "oksbi", "okhdfcbank", "okicici", "okaxis", "okbizaxis",
    "ybl", "ibl", "axl", "apl", "yapl", "waaxis", "wahdfcbank",
    "paytm", "upi", "sbi", "hdfcbank", "icici", "axisbank", "pnb", "fbl",
    "airtel", "freecharge", "jupiteraxis", "slc", "kotak",
]

# TLDs the URL detector will recognise in bare domains (no scheme).
URL_TLDS: list[str] = [
    "com", "in", "co", "io", "me", "org", "net", "app", "dev",
    "link", "ee", "ly", "gg", "xyz", "site", "page", "bio",
]

# Verbs that signal *asking* for an identifier (solicitation).
ASK_VERBS: list[str] = [
    "give", "send", "share", "drop", "tell", "pass", "whats", "what's",
    "what is", "lemme get", "can i get", "need your",
]

# Verbs that signal steering the conversation off-platform.
STEER_VERBS: list[str] = [
    "add", "find", "dm", "text", "call", "msg", "message", "ping", "reach",
    "catch", "move", "switch", "connect", "chat", "hit", "follow", "come",
]

# --- Block message tones (graduate by offence count) ------------------------
# {0} may be filled with a short, category-specific clause.
TONES: dict[str, list[str]] = {
    # offence 1 — gentle
    "gentle": [
        "Heads up — Matila keeps you both anonymous for now, so contact details, "
        "socials and numbers can't be shared yet. You'll be able to once you both "
        "choose to reveal. \U0001F49B",
    ],
    # offence 2 — firmer
    "firm": [
        "Let's keep it inside Matila — numbers, emails, UPI and social handles "
        "can't be shared during the anonymous chat. It's what keeps this safe for "
        "everyone.",
    ],
    # offence 3+ — serious but caring
    "serious": [
        "We've had to block this again. Repeatedly trying to share or ask for "
        "personal contact details can get your account limited — not because we "
        "want to, but to keep everyone safe. Please keep the conversation here.",
    ],
    # category nudge for solicitation (asking for the other person's details)
    "ask": [
        "You can't ask for their contact or socials yet — Matila stays anonymous "
        "until you both choose to reveal. \U0001F49B",
    ],
}


def export() -> dict:
    """JSON-serialisable ruleset for the client pre-send check (future FE
    endpoint). Mirrors the word-lists the backend scanner compiles from."""
    return {
        "version": RULESET_VERSION,
        "spelled_digits": SPELLED_DIGITS,
        "platform_words": PLATFORM_WORDS,
        "psp_handles": PSP_HANDLES,
        "url_tlds": URL_TLDS,
        "ask_verbs": ASK_VERBS,
        "steer_verbs": STEER_VERBS,
        "tones": TONES,
    }
