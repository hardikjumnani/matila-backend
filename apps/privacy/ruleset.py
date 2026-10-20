"""Veil ruleset — versioned, language-independent data the scanner compiles from.

Per-language keyword dictionaries now live in :mod:`apps.privacy.languages` and
are merged into one Aho-Corasick automaton by :mod:`apps.privacy.dictionaries`.
This module keeps the data that is language-independent: platform brand names,
UPI PSP handles, URL TLDs, the homoglyph (confusables) map, and the graduated
block-message tones. ``export()`` serialises everything for the client pre-send
mirror so the frontend stays in sync without an app release.

Deterministic only — no AI. Bump ``RULESET_VERSION`` whenever any list changes.
"""

from __future__ import annotations

RULESET_VERSION = "2026.10.12-v2.2"

# --- Platforms / contact nouns (language-independent brand + contact words) --
PLATFORM_WORDS: list[str] = [
    "instagram", "insta", "instagrm", "ig", "gram",
    "snapchat", "snap", "sc",
    "whatsapp", "whatsap", "watsapp", "whatzapp", "wsp", "wa",
    "telegram", "tele", "tgram", "tg",
    "discord", "disc",
    "signal", "messenger", "facebook", "fb", "twitter", "reddit", "linkedin",
    "gpay", "googlepay", "phonepe", "paytm", "bhim", "upi",
    "email", "gmail", "mail",
    "number", "mobile", "contact", "digits", "phone", "cell",
]

# UPI PSP handles (the part after '@' in a VPA).
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

# --- Confusables (homoglyph) map --------------------------------------------
# NFKC already folds fullwidth/compatibility forms; this covers cross-SCRIPT
# lookalikes (Cyrillic / Greek letters that render like Latin) which NFKC does
# NOT fold. Curated for the realistic evasion set, kept small to bound false
# positives (a full TR39 skeleton can replace this later if needed).
CONFUSABLES: dict[str, str] = {
    # Cyrillic (lowercase)
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x",
    "к": "k", "м": "m", "т": "t", "в": "b", "н": "h", "і": "i", "ј": "j",
    "ѕ": "s", "ԁ": "d", "г": "r", "п": "n", "л": "l", "д": "d", "з": "z",
    # Cyrillic (uppercase)
    "А": "a", "В": "b", "Е": "e", "К": "k", "М": "m", "Н": "h", "О": "o",
    "Р": "p", "С": "c", "Т": "t", "Х": "x", "У": "y",
    # Greek (lowercase)
    "α": "a", "ο": "o", "ρ": "p", "ε": "e", "ν": "v", "τ": "t", "κ": "k",
    "ι": "i", "μ": "u", "χ": "x", "γ": "y", "σ": "o", "υ": "u", "β": "b",
}
CONFUSABLES_TABLE = str.maketrans(CONFUSABLES)

# --- Block message tones (graduate by offence count) ------------------------
TONES: dict[str, list[str]] = {
    "gentle": [
        "Heads up. Matila keeps you both anonymous for now, so contact details, "
        "socials and numbers can't be shared yet. You'll be able to once you both "
        "choose to reveal. \U0001F49B",
    ],
    "firm": [
        "Let's keep it inside Matila. Personal details can't be shared during the "
        "anonymous chat. It's what keeps this safe for everyone.",
    ],
    "serious": [
        "We've had to block this again. Repeatedly trying to share or ask for "
        "personal contact details can get your account limited. It's not because we "
        "want to, but to keep everyone safe. Please keep the conversation here.",
    ],
    "ask": [
        "You can't ask for their contact or socials yet. Matila stays anonymous "
        "until you both choose to reveal. \U0001F49B",
    ],
    # meeting-coordination nudge
    "meet": [
        "Planning to meet offline isn't available while you're both anonymous. "
        "You can sort that out after you choose to reveal. \U0001F49B",
    ],
    # self-name nudge (the sender tried to reveal their own name)
    "name": [
        "Hold on. Sharing your name gives away your identity before the reveal. "
        "Keep it anonymous for now. You'll get to share it once you both reveal. "
        "\U0001F49B",
    ],
}


def export() -> dict:
    """JSON-serialisable ruleset for the client pre-send check. Mirrors the data
    the backend scanner compiles from (word-lists per language + global lists)."""
    from apps.privacy.languages import LANGUAGES

    return {
        "version": RULESET_VERSION,
        "languages": LANGUAGES,
        "platform_words": PLATFORM_WORDS,
        "psp_handles": PSP_HANDLES,
        "url_tlds": URL_TLDS,
        "confusables": CONFUSABLES,
        "tones": TONES,
    }
