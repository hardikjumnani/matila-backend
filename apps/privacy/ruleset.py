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

RULESET_VERSION = "2026.11.01-v2.5"

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
        "You're both anonymous for now, so contact details can't be shared yet. "
        "You can once you both reveal. \U0001F49B",
    ],
    "firm": [
        "Keep personal details out of the chat while you're anonymous. It keeps "
        "everyone safe.",
    ],
    "serious": [
        "Blocked again. Repeatedly sharing contact details can limit your account. "
        "Please keep it in the chat.",
    ],
    "ask": [
        "You can't ask for their contact yet. Wait until you both reveal. \U0001F49B",
    ],
    # meeting-coordination nudge
    "meet": [
        "Meeting up can't be arranged while you're anonymous. Sort it out after you "
        "reveal. \U0001F49B",
    ],
    # non-English script nudge (message contained non-Latin letters)
    "english": [
        "Please chat in English for now. \U0001F49B",
    ],
    # self-name nudge (the sender tried to reveal their own name)
    "name": [
        "Sharing your name gives you away before the reveal. Keep it for later. "
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
