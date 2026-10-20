"""Per-language keyword dictionaries for Veil (deterministic, no AI).

Each language contributes romanized word/phrase lists per signal category. The
loader (:mod:`apps.privacy.dictionaries`) merges these into ONE Aho-Corasick
automaton, so adding a language costs memory at startup but nothing per message
(matching is O(message length), independent of dictionary size).

Signal categories
-----------------
- ``ask_verbs``        asking for an identifier (SOLICITATION)
- ``steer_verbs``      steering off-platform (STEERING)
- ``invite_words``     proposing/accepting an offline meet (INVITE)
- ``destination_words``a physical venue / meeting point (DESTINATION)
- ``time_words``       a time / schedule reference (TIME)
- ``direction_words``  how to reach / locate someone (DIRECTIONS)
- ``location_pin``     requesting/offering a location pin (LOCATION_PIN)
- ``spelled_digits``   number words, for the cross-message Number Reassembler

NOTE: these are curated STARTER lists. They are deliberately conservative where a
token collides with ordinary English/other-language words (ambiguous number
words like Gujarati "be"=2 are omitted from ``spelled_digits`` to keep the
reassembler's false-positive rate low). Expansion needs native-speaker review +
the per-language test corpus (see docs/VEIL_V2_PLAN.md). Platform brand names,
PSP handles and URL TLDs are language-independent and live in ``ruleset.py``.
"""

from __future__ import annotations

# Shared, language-independent number words (unambiguous ones only).
_EN_DIGITS = {
    "zero": "0", "oh": "0", "nought": "0",
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9",
}

LANGUAGES: dict[str, dict] = {
    "english": {
        "ask_verbs": [
            "give", "send", "share", "drop", "tell", "pass", "whats", "what's",
            "what is", "lemme get", "can i get", "need your", "whatsapp me",
            # 2-word phrases so their glued collapsed forms (giveme, sendme) match.
            "give me", "send me", "share your", "drop your", "need your",
        ],
        "steer_verbs": [
            "add", "find", "dm", "text", "call", "msg", "message", "ping", "reach",
            "catch", "move", "switch", "connect", "chat", "hit", "follow", "come",
            # 2-word phrases so glued forms (addme, textme, dmme) match collapsed.
            "add me", "text me", "dm me", "find me", "msg me", "message me",
            "ping me", "reach me", "hit me up",
        ],
        "invite_words": [
            "let's meet", "lets meet", "wanna meet", "shall we meet", "we can meet",
            "can we meet", "meet up", "meet me", "meet outside", "meet irl",
            "meet in person", "see you there", "come over", "come meet", "catch up",
            "let's hang", "lets hang", "hang out",
        ],
        "destination_words": [
            "canteen", "cafe", "cafeteria", "coffee shop", "library", "lib",
            "hostel", "mess", "ground", "parking", "gate", "main gate", "campus",
            "metro", "metro station", "station", "bus stop", "mall", "park",
            "food court", "block", "cabin", "amphitheatre", "amphi", "quad",
            "lawn", "lawns", "corridor",
        ],
        "time_words": [
            "today", "tonight", "tomorrow", "tmrw", "morning", "afternoon",
            "evening", "noon", "midnight", "am", "pm", "o'clock", "oclock",
            "right now", "in an hour", "in 10 mins", "after class", "after college",
            "lunch time", "sharp",
        ],
        "direction_words": [
            "how to reach", "come to", "reach me", "find me at", "i'll be at",
            "ill be at", "i am at", "i'm at", "waiting at", "near the", "outside the",
            "in front of", "i'll come", "ill come", "pick you up", "pick me up",
        ],
        "location_pin": [
            "share location", "send location", "share live location", "send pin",
            "drop a pin", "drop pin", "my location", "location pin", "live location",
            "google maps link", "maps link",
            "share your location", "send your location", "drop your location",
            "share ur location", "send ur location",
        ],
        "spelled_digits": _EN_DIGITS,
    },
    "hindi": {
        "ask_verbs": ["de", "dedo", "de do", "bhej", "bhejo", "bata", "batao", "bol"],
        "steer_verbs": ["add kar", "dm kar", "msg kar", "call kar", "message kar",
                        "ping kar", "follow kar", "jud", "aa ja insta"],
        "invite_words": ["milte hai", "milte hain", "mil lete", "milna", "milo",
                         "chalo milte", "aa jao", "aaja", "aa ja", "chal milte",
                         "baahar milte", "bahar milte"],
        "destination_words": ["canteen", "mess", "hostel", "gate", "maidan",
                              "ground", "cafe", "library", "metro", "station",
                              "chowk", "adda"],
        "time_words": ["aaj", "kal", "abhi", "subah", "shaam", "sham", "dopahar",
                       "raat", "baje", "baad me", "lunch ke baad"],
        "direction_words": ["aa jao", "pahunch", "pahuch", "bahar aa", "baahar aa",
                            "mai hu", "main hu", "ruko wahan", "yahan aa", "wahan aa"],
        "location_pin": ["location bhej", "location de", "pin bhej", "live location",
                         "apni location"],
        # Hinglish number words (conservative: omit "do"=2, "no"/"to" collisions).
        "spelled_digits": {
            "ek": "1", "teen": "3", "char": "4", "paanch": "5", "panch": "5",
            "chhe": "6", "che": "6", "chah": "6", "saat": "7", "sat": "7",
            "aath": "8", "ath": "8", "nau": "9", "shunya": "0",
        },
    },
    "tamil": {
        "ask_verbs": ["kudu", "kudunga", "anupu", "anuppu", "sollu", "solunga"],
        "steer_verbs": ["add pannu", "dm pannu", "message pannu", "call pannu",
                        "follow pannu", "msg pannu"],
        "invite_words": ["meet pannalaam", "paakalaam", "paarkalaam", "varen",
                         "vaanga", "vaa", "sandhippom", "veliya meet"],
        "destination_words": ["canteen", "mess", "hostel", "gate", "ground",
                              "library", "metro", "station", "kadai"],
        "time_words": ["inniki", "naalaiku", "ippo", "kaalai", "maalai", "iravu",
                       "mani", "lunch kku aprom"],
        "direction_words": ["vaa inga", "naan irukken", "wait pannu", "veliya vaa"],
        "location_pin": ["location anupu", "location share", "pin anupu",
                         "live location"],
        "spelled_digits": {
            "onnu": "1", "rendu": "2", "moonu": "3", "naalu": "4", "anju": "5",
            "aaru": "6", "yezhu": "7", "ettu": "8", "onbathu": "9", "poojyam": "0",
        },
    },
    "telugu": {
        "ask_verbs": ["ivvu", "pampu", "pampinchu", "cheppu", "ivvandi"],
        "steer_verbs": ["add cheyyi", "dm cheyyi", "message cheyyi", "call cheyyi",
                        "follow avvu", "msg cheyyi"],
        "invite_words": ["kaluddam", "kaludam", "kaluddama", "veltam", "ravu",
                         "randi", "bayata kaluddam", "meet avvu"],
        "destination_words": ["canteen", "mess", "hostel", "gate", "ground",
                              "library", "metro", "station"],
        "time_words": ["ivala", "repu", "ippudu", "udayam", "sayantram", "ratri",
                       "gantalaki", "lunch tarvata"],
        "direction_words": ["ikkada raa", "nenu unna", "wait cheyyi", "bayataki raa"],
        "location_pin": ["location pampu", "location share", "pin pampu",
                         "live location"],
        "spelled_digits": {
            "okati": "1", "rendu": "2", "moodu": "3", "nalugu": "4", "aidu": "5",
            "aaru": "6", "edu": "7", "enimidi": "8", "tommidi": "9", "sunna": "0",
        },
    },
    "kannada": {
        "ask_verbs": ["kodu", "kodi", "kalisu", "kaluhisu", "helu", "heli"],
        "steer_verbs": ["add maadu", "dm maadu", "message maadu", "call maadu",
                        "follow maadu", "msg maadu"],
        "invite_words": ["sigona", "sikkona", "meet maadona", "banni", "baa",
                         "horage sigona", "bheti"],
        "destination_words": ["canteen", "mess", "hostel", "gate", "ground",
                              "library", "metro", "station"],
        "time_words": ["ivatt", "naale", "eega", "belagge", "sanje", "raatri",
                       "ganteege", "lunch aamele"],
        "direction_words": ["illi baa", "naanu idini", "wait maadu", "horage baa"],
        "location_pin": ["location kalisu", "location share", "pin kalisu",
                         "live location"],
        "spelled_digits": {
            "ondu": "1", "eradu": "2", "mooru": "3", "nalku": "4", "aidu": "5",
            "aaru": "6", "elu": "7", "entu": "8", "ombattu": "9", "sonne": "0",
        },
    },
    "malayalam": {
        "ask_verbs": ["tharu", "tharamo", "ayakku", "ayakkoo", "parayu", "para"],
        "steer_verbs": ["add cheyyu", "dm cheyyu", "message cheyyu", "call cheyyu",
                        "follow cheyyu", "msg cheyyu"],
        "invite_words": ["kaanaam", "kandukaanaam", "meet cheyyaam", "varu", "vaa",
                         "purath kaanaam", "oth kaanaam"],
        "destination_words": ["canteen", "mess", "hostel", "gate", "ground",
                              "library", "metro", "station"],
        "time_words": ["innu", "naale", "ippo", "raavile", "vaikittu", "raathri",
                       "manikku", "lunch kazhinju"],
        "direction_words": ["ivide vaa", "njaan undu", "wait cheyyu", "purath vaa"],
        "location_pin": ["location ayakku", "location share", "pin ayakku",
                         "live location"],
        "spelled_digits": {
            "onnu": "1", "randu": "2", "moonu": "3", "naalu": "4", "anju": "5",
            "aaru": "6", "ezhu": "7", "ettu": "8", "onpathu": "9", "poojyam": "0",
        },
    },
    "marathi": {
        "ask_verbs": ["de", "dya", "pathav", "pathava", "sang", "sanga"],
        "steer_verbs": ["add kar", "dm kar", "message kar", "call kar",
                        "follow kar", "msg kar"],
        "invite_words": ["bhetuya", "bhetu", "bhetuyat", "ye", "ya", "baher bhetu",
                         "bhet"],
        "destination_words": ["canteen", "mess", "hostel", "gate", "maidan",
                              "ground", "library", "metro", "station", "katta"],
        "time_words": ["aaj", "udya", "aata", "sakali", "sandhyakali", "ratri",
                       "vajta", "lunch nantar"],
        "direction_words": ["ikde ye", "mi aahe", "thamb", "baher ye"],
        "location_pin": ["location pathav", "location share", "pin pathav",
                         "live location"],
        "spelled_digits": {
            "ek": "1", "teen": "3", "chaar": "4", "paach": "5", "saha": "6",
            "saat": "7", "aath": "8", "nau": "9", "shunya": "0",
        },
    },
    "bengali": {
        "ask_verbs": ["dao", "de", "pathao", "pathiye dao", "bolo", "bol"],
        "steer_verbs": ["add koro", "dm koro", "message koro", "call koro",
                        "follow koro", "msg koro"],
        "invite_words": ["dekha korbo", "dekha hobe", "dekha koro", "esho", "aay",
                         "baire dekha", "meet korbo"],
        "destination_words": ["canteen", "mess", "hostel", "gate", "maath",
                              "ground", "library", "metro", "station", "mor"],
        "time_words": ["aaj", "kal", "ekhon", "sokaal", "bikel", "raat",
                       "tay", "lunch er por"],
        "direction_words": ["ekhane aay", "ami achi", "daran", "baire aay"],
        "location_pin": ["location pathao", "location share", "pin pathao",
                         "live location"],
        "spelled_digits": {
            "ek": "1", "dui": "2", "tin": "3", "char": "4", "paanch": "5",
            "chhoy": "6", "saat": "7", "aat": "8", "noy": "9", "shunno": "0",
        },
    },
    "gujarati": {
        "ask_verbs": ["aap", "aapo", "mokal", "mokalo", "kaho", "kehjo"],
        "steer_verbs": ["add karo", "dm karo", "message karo", "call karo",
                        "follow karo", "msg karo"],
        "invite_words": ["malie", "maliye", "malva", "aavo", "aav", "bahar malie",
                         "meet karie"],
        "destination_words": ["canteen", "mess", "hostel", "gate", "ground",
                              "library", "metro", "station", "chowk"],
        "time_words": ["aaje", "kaale", "atyare", "savare", "saanje", "raate",
                       "vagye", "lunch pachhi"],
        "direction_words": ["ahi aavo", "hu chhu", "ubha raho", "bahar aavo"],
        "location_pin": ["location mokal", "location share", "pin mokal",
                         "live location"],
        # "be"=2 omitted (collides with English "be"); conservative set.
        "spelled_digits": {
            "ek": "1", "tran": "3", "char": "4", "paanch": "5", "chha": "6",
            "saat": "7", "aath": "8", "nav": "9", "shunya": "0",
        },
    },
    "punjabi": {
        "ask_verbs": ["de", "deo", "ghall", "ghallo", "dass", "dasso"],
        "steer_verbs": ["add kar", "dm kar", "message kar", "call kar",
                        "follow kar", "msg kar"],
        "invite_words": ["milde haan", "milde", "milna", "aao", "aaja", "bahar milde",
                         "meet karie"],
        "destination_words": ["canteen", "mess", "hostel", "gate", "ground",
                              "library", "metro", "station", "adda"],
        "time_words": ["ajj", "kal", "hune", "savere", "shaam", "raat",
                       "vaje", "lunch baad"],
        "direction_words": ["ithe aa", "main haan", "ruk", "bahar aa"],
        "location_pin": ["location ghall", "location share", "pin ghall",
                         "live location"],
        "spelled_digits": {
            "ikk": "1", "ik": "1", "tinn": "3", "char": "4", "panj": "5",
            "chhe": "6", "satt": "7", "assi": "8", "nau": "9", "sunn": "0",
        },
    },
}

# Severity per signal category (HIGH = block-worthy on its own or in combination).
CATEGORY_KINDS = (
    "ask_verbs", "steer_verbs", "invite_words", "destination_words",
    "time_words", "direction_words", "location_pin", "spelled_digits",
)
