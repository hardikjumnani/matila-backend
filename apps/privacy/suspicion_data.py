"""Deterministic data for the Suspicion engine ("second-hand Veil").

Language-independent / lexical data the non-blocking :class:`SuspicionGuard`
compiles from. Pure data only (no AI). Bump ``SUSPICION_RULE_VERSION`` whenever
any list changes.

The suspicion layer NEVER blocks a message; it emits weighted soft signals that
are recorded for admin assessment and for tuning Veil. It is backend-only and
admin-only; the user is never shown anything. A false positive here only adds an
admin-review row, so these lists can be broader than Veil's, but they are kept
CLASSED so that "ambient" behaviour (romanized Hindi, non-Latin, gibberish) which
is normal for this user base never drives a user up the admin queue.
"""

from __future__ import annotations

SUSPICION_RULE_VERSION = "2026.11.01-suspicion-v3"

# -- Signal classes -----------------------------------------------------------
# ambient     = normal for this user base (romanized Hindi, non-Latin, gibberish).
#               Recorded for context but EXCLUDED from the priority (ranking/tier)
#               score, so a legitimate heavy Hindi-romanizer never climbs the queue.
# structural  = obfuscation mechanics (invisible chars, separator splits, leet).
# pii         = sub-threshold PII-leak tells (the ones that matter).
# behavioral  = cross-message / cadence patterns + a recorded Veil hard-block.
CLASS_AMBIENT = "ambient"
CLASS_STRUCTURAL = "structural"
CLASS_PII = "pii"
CLASS_BEHAVIORAL = "behavioral"

SIGNAL_CLASS: dict[str, str] = {
    "NON_LATIN_SCRIPT": CLASS_AMBIENT,
    "ROMANIZED_INDIC": CLASS_AMBIENT,
    "GIBBERISH": CLASS_AMBIENT,
    "OBFUSCATION_INVISIBLE": CLASS_STRUCTURAL,
    "OBFUSCATION_SPLIT": CLASS_STRUCTURAL,
    "OBFUSCATION_LEET": CLASS_STRUCTURAL,
    "NEAR_PHONE": CLASS_PII,
    "PARTIAL_DIGITS": CLASS_PII,
    "DIGIT_DENSITY": CLASS_PII,
    "BRAND_MENTION": CLASS_PII,
    "HANDLE_SOFT": CLASS_PII,
    "SELFNAME_SOFT": CLASS_PII,
    "REVERSAL_HINT": CLASS_PII,
    "CONTACT_SOFT": CLASS_PII,
    "ENTROPY_TOKEN": CLASS_PII,
    "DIGIT_DRIP": CLASS_BEHAVIORAL,
    "CHAR_BURST": CLASS_BEHAVIORAL,
    "CROSS_MESSAGE": CLASS_BEHAVIORAL,
    "BLOCKED_LEAK": CLASS_BEHAVIORAL,
    # Tier-3 meeting/location (sub-threshold rendezvous Veil does not hard-block).
    "MEETING_SOFT": CLASS_PII,       # an invite paired with a vague place
    "LOCATION_SOFT": CLASS_AMBIENT,  # lone place hints (benign narrowing) -> context only
}

# Signals excluded from the priority (tier/ranking) score. They still record.
AMBIENT_SIGNALS: frozenset[str] = frozenset(
    s for s, c in SIGNAL_CLASS.items() if c == CLASS_AMBIENT
)

# Default per-signal weights (admin-overridable via app_config
# ``suspicion_signal_weights``). A message's score is the sum of the weights of
# the DISTINCT signals it triggers (each signal fires at most once). SINGLE SOURCE
# OF TRUTH: configuration defaults import this map (no duplication).
DEFAULT_SIGNAL_WEIGHTS: dict[str, int] = {
    # ambient (down-weighted; excluded from the priority score anyway)
    "NON_LATIN_SCRIPT": 1,
    "ROMANIZED_INDIC": 1,
    "GIBBERISH": 2,
    # structural
    "OBFUSCATION_INVISIBLE": 3,
    "OBFUSCATION_SPLIT": 2,
    "OBFUSCATION_LEET": 2,
    # pii
    "NEAR_PHONE": 3,
    "PARTIAL_DIGITS": 3,
    "DIGIT_DENSITY": 2,
    "BRAND_MENTION": 2,
    "HANDLE_SOFT": 3,
    "SELFNAME_SOFT": 4,
    "REVERSAL_HINT": 2,
    "CONTACT_SOFT": 2,
    "ENTROPY_TOKEN": 2,
    # behavioral
    "DIGIT_DRIP": 3,
    "CHAR_BURST": 2,
    "CROSS_MESSAGE": 4,
    "BLOCKED_LEAK": 5,
    # meeting / location (soft)
    "MEETING_SOFT": 3,
    "LOCATION_SOFT": 1,
}

# Decay + tier defaults (admin-overridable). The priority score decays with this
# half-life so it reflects CURRENT risk, not a lifetime tally; tiers are review
# LABELS only (they never block or act on the account).
DEFAULT_DECAY_HALF_LIFE_DAYS = 14
DEFAULT_TIER_THRESHOLDS: dict[str, int] = {"WATCH": 3, "ELEVATED": 8, "HIGH": 16}

# -- Non-Latin script ranges (letters only; emoji/symbols are excluded) -------
NON_LATIN_RANGES: tuple[tuple[int, int], ...] = (
    (0x0370, 0x03FF),  # Greek
    (0x0400, 0x04FF),  # Cyrillic
    (0x0600, 0x06FF),  # Arabic
    (0x0900, 0x097F),  # Devanagari
    (0x0980, 0x09FF),  # Bengali
    (0x0A00, 0x0A7F),  # Gurmukhi
    (0x0A80, 0x0AFF),  # Gujarati
    (0x0B00, 0x0B7F),  # Oriya
    (0x0B80, 0x0BFF),  # Tamil
    (0x0C00, 0x0C7F),  # Telugu
    (0x0C80, 0x0CFF),  # Kannada
    (0x0D00, 0x0D7F),  # Malayalam
    (0x3040, 0x30FF),  # Hiragana + Katakana
    (0x4E00, 0x9FFF),  # CJK Unified Ideographs
    (0xAC00, 0xD7AF),  # Hangul syllables
)

# Zero-width / invisible characters used to break up needles.
ZERO_WIDTH_CODES: frozenset[int] = frozenset(
    ord(c) for c in "​‌‍⁠﻿­"
)

# -- Romanized Indic / code-mix markers --------------------------------------
ROMANIZED_INDIC_MARKERS: frozenset[str] = frozenset(
    {
        # Hindi / Urdu
        "hai", "hain", "kya", "kyun", "kyunki", "nahi", "nahin", "mera", "meri",
        "tera", "teri", "tumhe", "tumhara", "mujhe", "mujhse", "aap", "aapka",
        "bhej", "bhejo", "bhejdo", "bhai", "yaar", "yar", "acha", "accha",
        "theek", "thik", "kaise", "kaisa", "kahan", "kahaan", "kab", "matlab",
        "batao", "dekho", "chalo", "karo", "karna", "raha", "rahi", "rahe",
        "hoon", "abhi", "bilkul", "zaroor", "pata", "kuch", "kuchh", "bahut",
        "thoda", "milte", "milna", "milo", "milenge", "jaldi", "bata",
        # Tamil
        "enna", "epdi", "epudu", "ennmodu", "vaa", "vaanga", "machi", "macha",
        "thala", "seri",
        # Telugu
        "nuvvu", "cheyi", "ledu", "ekkada", "emchestunnav", "ela", "ventane",
    }
)

# -- Platform brand words for BRAND_MENTION / HANDLE_SOFT ----------------------
# Distinctive brand names (not generic nouns like "number"/"email", which are too
# common for a soft signal). A bare brand mention is BRAND_MENTION; a brand +
# connector + a letters-only value ("my insta is cool") is HANDLE_SOFT.
BRAND_WORDS: frozenset[str] = frozenset(
    {
        "instagram", "insta", "instagrm", "snapchat", "snap", "whatsapp",
        "whatsap", "watsapp", "telegram", "discord", "gpay", "googlepay",
        "phonepe", "paytm",
    }
)

# -- Contact-intent phrases (CONTACT_SOFT) ------------------------------------
# Ask/steer phrasing with NO platform and NO number: too weak for a Veil block
# ("find me", "text me") but worth a soft note. Matched as substrings of the
# folded view, so glued forms ("textme") are covered too.
CONTACT_INTENT_MARKERS: tuple[str, ...] = (
    "find me", "add me", "text me", "dm me", "message me", "msg me", "ping me",
    "reach me", "hit me up", "follow me", "catch me", "search my", "same user",
    "same username", "find my", "look me up",
)

# -- Meeting / location soft signals (Tier 3) ---------------------------------
# Veil hard-blocks a validator-certain rendezvous; these catch the sub-threshold
# cousins for admin CONTEXT only: an invite + a vague place (MEETING_SOFT), or
# several lone place hints with no invite (LOCATION_SOFT, ambient -> not ranked, so
# ordinary getting-to-know narrowing like hostel/year/city never climbs the queue).
INVITE_MARKERS: tuple[str, ...] = (
    "lets meet", "let's meet", "wanna meet", "shall we meet", "can we meet",
    "meet up", "meet me", "come over", "come meet", "catch up", "see you there",
    "milte hain", "milte hai", "aa jao", "milte hain",
)
VENUE_MARKERS: frozenset[str] = frozenset({
    "resort", "hotel", "cafe", "canteen", "hostel", "station", "metro", "mall",
    "beach", "restaurant", "dhaba", "library", "ground", "airport", "cinema",
    "stadium", "gate", "campus", "park", "pg", "dorm",
})

# -- Spelled-digit collision words (PARTIAL_DIGITS only) ----------------------
# Number words that collide with English, deliberately kept OUT of Veil's phone
# reassembler. Here they only count toward the soft PARTIAL_DIGITS signal.
COLLISION_DIGITS: frozenset[str] = frozenset(
    {"do", "to", "be", "for", "ate", "won", "tree", "fife", "oh"}
)

# Reversal cue words (REVERSAL_HINT), romanized included.
REVERSAL_CUES: tuple[str, ...] = ("backward", "backwards", "reverse", "reversed",
                                  "ulta", "ultaa", "palindrome")

# -- Gibberish detection ------------------------------------------------------
VOWELS: frozenset[str] = frozenset("aeiouy")

GIBBERISH_ALLOWLIST: frozenset[str] = frozenset(
    {
        "lol", "lmao", "lmfao", "rofl", "brb", "idk", "idc", "omg", "omw",
        "tbh", "imo", "imho", "btw", "fyi", "gtg", "ttyl", "ikr", "smh", "wyd",
        "hbu", "pls", "plz", "thx", "ngl", "bruh", "haha", "hahaha", "hehe",
        "hmm", "hmmm", "okk", "yep", "nope", "yaas", "xoxo", "muah",
    }
)

COMMON_BIGRAMS: frozenset[str] = frozenset(
    {
        "th", "he", "in", "er", "an", "re", "on", "at", "en", "nd", "ti", "es",
        "or", "te", "of", "ed", "is", "it", "al", "ar", "st", "to", "nt", "ng",
        "se", "ha", "as", "ou", "io", "le", "ve", "co", "me", "de", "hi", "ri",
        "ro", "ic", "ne", "ea", "ra", "ce", "li", "ch", "ll", "be", "ma", "si",
        "om", "ur", "ca", "el", "ta", "la", "ns", "di", "fo", "ho", "pe", "ec",
        "pr", "no", "us", "ou", "ea", "lo", "wi", "ge", "ess", "oo", "ee", "em",
        "ac", "ol", "rt", "ut", "ad", "sa", "so", "ir", "et", "im", "ot", "by",
        "ca", "sh", "wh", "ul", "il", "ow", "na", "ay", " ", "ter", "we", "do",
        "ev", "ba", "fe", "fi", "pa", "po", "wa", "ke", "ck", "mo", "bl", "br",
        "cl", "cr", "dr", "fl", "fr", "gl", "gr", "pl", "sc", "sk", "sl", "sm",
        "sn", "sp", "sq", "sw", "tr", "tw", "ss", "ff", "oe", "ue", "ui", "ya",
        "yo", "ye", "um", "un", "up", "ab", "ag", "ap", "av", "aw", "ex", "if",
        "ig", "ip", "ks", "ld", "lf", "lk", "lp", "ly", "mp", "nc", "ni", "nk",
        "op", "rd", "rk", "rm", "rn", "rp", "rs", "rv", "ry", "ts", "ty", "vi",
        "vo", "mu", "bu", "cu", "du", "fu", "gu", "hu", "ju", "lu", "nu", "pu",
        "ru", "su", "tu",
    }
)
