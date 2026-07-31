"""
Deterministic anonymous aliases for chat participants.

While a chat is anonymous the client needs a stable, human-friendly label for
the other person instead of their real name. The alias is derived purely from
(chat_id, user_id) via a hash, so it is:

- stable — the same partner in the same chat always gets the same alias,
- storage-free — no column or migration,
- unique-ish within a chat — the two participants hash to different words.

Aliases are cosmetic only; identity is still governed by ``current_phase``.
"""

from __future__ import annotations

import hashlib

_ADJECTIVES = (
    "Amber",
    "Azure",
    "Brave",
    "Calm",
    "Clever",
    "Cosmic",
    "Crimson",
    "Curious",
    "Gentle",
    "Golden",
    "Hidden",
    "Jolly",
    "Lucky",
    "Mellow",
    "Mystic",
    "Noble",
    "Quiet",
    "Rapid",
    "Scarlet",
    "Silent",
    "Silver",
    "Sunny",
    "Swift",
    "Velvet",
)
_NOUNS = (
    "Otter",
    "Falcon",
    "Panda",
    "Fox",
    "Owl",
    "Lynx",
    "Heron",
    "Robin",
    "Koala",
    "Raven",
    "Tiger",
    "Wolf",
    "Bison",
    "Crane",
    "Dolphin",
    "Eagle",
    "Hawk",
    "Ibis",
    "Jaguar",
    "Puma",
    "Quokka",
    "Seal",
    "Swan",
    "Yak",
)


def anonymous_alias(chat_id: str, user_id: str) -> str:
    """Return a stable two-word alias for a user within a chat."""
    digest = hashlib.sha256(f"{chat_id}:{user_id}".encode()).digest()
    adjective = _ADJECTIVES[digest[0] % len(_ADJECTIVES)]
    noun = _NOUNS[digest[1] % len(_NOUNS)]
    return f"{adjective} {noun}"
