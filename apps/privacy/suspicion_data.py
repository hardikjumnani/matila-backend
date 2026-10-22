"""Deterministic data for the Suspicion engine ("second-hand Veil").

Language-independent / lexical data the non-blocking :class:`SuspicionGuard`
compiles from. Pure data only (no AI). Bump ``SUSPICION_RULE_VERSION`` whenever
any list changes.

The suspicion layer NEVER blocks a message; it emits weighted soft signals that
are recorded for admin assessment and for tuning Veil. Precision matters less
than it does for Veil (a false positive here only adds an admin-review row, it
does not hinder a user), but the lists are still kept conservative to keep the
admin feed usable.
"""

from __future__ import annotations

SUSPICION_RULE_VERSION = "2026.10.23-suspicion-v1"

# Default per-signal weights (admin-overridable via app_config
# ``suspicion_signal_weights``). A message's score is the sum of the weights of
# the DISTINCT signals it triggers (each signal fires at most once).
DEFAULT_SIGNAL_WEIGHTS: dict[str, int] = {
    "NON_LATIN_SCRIPT": 2,
    "ROMANIZED_INDIC": 2,
    "GIBBERISH": 2,
    "OBFUSCATION": 3,
    "NEAR_MISS": 3,
}

# -- Non-Latin script ranges (letters only; emoji/symbols are excluded) -------
# Presence of any character in these blocks fires NON_LATIN_SCRIPT. Accented
# Latin (Latin-1 Supplement "café", "naïve") is intentionally NOT here.
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
# Distinctive romanized Hindi/Tamil/Telugu function words that essentially never
# appear in ordinary English. A single marker fires ROMANIZED_INDIC. Ambiguous
# tokens that collide with English ("sun", "me", "to", "he") are deliberately
# excluded. There is no standard romanization, so this is a signal, not a
# classifier (see the plan's research notes).
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

# -- Platform brand words for the NEAR_MISS signal ----------------------------
# Only distinctive brand names (not generic words like "number"/"email", which
# are too common for a soft signal). A brand mention that did not trip a Veil
# block is a borderline worth noting.
BRAND_WORDS: frozenset[str] = frozenset(
    {
        "instagram", "insta", "instagrm", "snapchat", "snap", "whatsapp",
        "whatsap", "watsapp", "telegram", "discord", "gpay", "googlepay",
        "phonepe", "paytm",
    }
)

# -- Gibberish detection ------------------------------------------------------
VOWELS: frozenset[str] = frozenset("aeiouy")

# Common chat tokens an aggressive gibberish check might otherwise flag.
GIBBERISH_ALLOWLIST: frozenset[str] = frozenset(
    {
        "lol", "lmao", "lmfao", "rofl", "brb", "idk", "idc", "omg", "omw",
        "tbh", "imo", "imho", "btw", "fyi", "gtg", "ttyl", "ikr", "smh", "wyd",
        "hbu", "pls", "plz", "thx", "ngl", "bruh", "haha", "hahaha", "hehe",
        "hmm", "hmmm", "okk", "yep", "nope", "yaas", "xoxo", "muah",
    }
)

# A compact set of common English bigrams. A real word is mostly made of these;
# keyboard mash ("ytjkacvzw") is mostly not. Used to score letter-sequence
# plausibility.
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
