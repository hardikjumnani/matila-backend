"""Muffle ruleset — tiered profanity lists + whitelist + masking config.

Single source of truth for the Muffle engine (see docs/MUFFLE_PROFANITY_PLAN.md).
Matching is whole-word on a leet/stretch-tolerant form, so substrings inside clean
words are never hit (the Scunthorpe guard) — the WHITELIST is a belt-and-suspenders
layer on top.

The tier BOUNDARY is a product/values decision and is meant to be curated by the
owner. These lists are a functional starting point, deliberately conservative:
  - T0 (casual): left completely untouched.
  - T1 (harsh/targeted): partially masked.
  - T2 (slur/hate): partially masked AND flagged for review.

NOTE: the worst identity slurs (racial / caste / communal) are intentionally NOT
spelled out here; they should be seeded into T2 from an access-controlled, curated
dataset (e.g. LDNOOBW, HASOC/HinTox-derived) during review. The few T2 entries
below exist only so the pipeline is functional and testable.
"""

from __future__ import annotations

RULESET_VERSION = "2026.10.10-v1.1"

# --- Masking config (sparse partial; keeps the word readable) ---------------
MASK_CHAR = "*"
MASK_STRIDE = 3   # mask every Nth interior character
MASK_START = 2    # first interior index to consider masking
MIN_MASK_LEN = 4  # words shorter than this are never masked
MIN_PHRASE_WORDS = 2  # phrase entries shorter than this are ignored

# --- T0: casual / mild — ALLOWED, never masked ------------------------------
T0_CASUAL = [
    "fuck", "fucks", "fuckin", "fucking", "fucked", "fck", "fuk",
    "shit", "shite", "shitty", "shits",
    "damn", "damnit", "dammit", "goddamn",
    "crap", "crappy", "ass", "arse", "asses", "hell",
    "bloody", "piss", "pissed", "bastard", "bitch", "bitches",
    "dick", "cock", "prick", "wtf", "stfu", "bs",
]

# --- T1: harsh / targeted — MASKED ------------------------------------------
T1_HARSH = [
    "motherfucker", "motherfuckers", "motherfuckin", "motherfucking",
    "fucker", "fuckers", "fuckface", "fuckwit", "fuckhead",
    "cocksucker", "dickhead", "asshole", "assholes", "dumbass", "jackass",
    "dipshit", "cockhead", "cunt", "cunts", "twat", "wanker",
    # Strong Hinglish gaalis (romanised). Family/sexual-targeted.
    "madarchod", "madarchode", "behenchod", "bhenchod", "bhosdike",
    "bhosdika", "bhosdiwala", "chutiya", "chutiye", "chutiyapa",
    "gaandu", "gandu", "lauda", "lund", "randi", "harami", "haramzada",
]

# --- T2: slur / hate — MASKED + FLAGGED (owner expands from curated lists) ---
T2_SLUR = [
    "retard", "retards", "retarded",
    "faggot", "faggots", "fag", "fags",
    # + racial / caste / communal / ableist slurs seeded from a curated,
    #   access-controlled dataset during review (intentionally not listed here).
]

# --- T1 phrases: harsh multi-word — MASKED (sparse, across the span) ---------
# Stored normalised: lowercase, single-spaced, no punctuation. The matcher is
# stretch/leet-tolerant per word and separator-tolerant between words.
T1_PHRASES = [
    "son of a bitch", "son of a whore",
    "piece of shit", "piece of garbage",
    "fuck you", "fuck off", "fuck you too",
    "go fuck yourself", "go to hell", "shut the fuck up",
    "suck my dick", "eat shit", "eat a dick", "kiss my ass",
    # Hinglish (romanised) — family/sexual-targeted.
    "teri maa ki", "teri maa ka", "teri maa ki chut", "maa ki chut",
    "behen ke laude", "bhen ke lode", "teri behen ki", "maa chuda",
    "teri maa ko",
]

# --- T2 phrases: slur/hate multi-word — MASKED + FLAGGED ---------------------
# Seeded from the curated, access-controlled dataset during review (caste /
# communal / racial / homophobic phrases). Intentionally empty here.
T2_PHRASES: list[str] = []

# --- Whitelist: clean words to never flag (Scunthorpe guard) -----------------
WHITELIST = [
    "class", "classic", "classes", "assassin", "assassinate", "assess",
    "assessment", "assume", "assumption", "bass", "grass", "pass", "passage",
    "passed", "compass", "cockpit", "cocktail", "scunthorpe", "shuttlecock",
    "analysis", "analyst", "therapist", "therapists", "cumulative",
    "circumstance", "document", "pistachio",
]


def export() -> dict:
    """JSON-serialisable ruleset. NOTE: T2 slurs are omitted from the client
    export by default — masking is server-authoritative, so the client never
    needs the slur list to render already-masked text."""
    return {
        "version": RULESET_VERSION,
        "mask": {
            "char": MASK_CHAR,
            "stride": MASK_STRIDE,
            "start": MASK_START,
            "min_len": MIN_MASK_LEN,
            "min_phrase_words": MIN_PHRASE_WORDS,
        },
        "t0_casual": T0_CASUAL,
        "t1_harsh": T1_HARSH,
        "t1_phrases": T1_PHRASES,  # T2 phrases/words omitted (server-authoritative)
        "whitelist": WHITELIST,
    }
