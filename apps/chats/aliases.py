"""
Deterministic anonymous aliases for chat participants.

While a chat is anonymous the client needs a stable, human-friendly label for
the other person instead of their real name. The alias is derived purely from
(chat_id, user_id) via a hash, so it is:

- stable — the same partner in the same chat always gets the same alias,
- storage-free — no column or migration.

The label is the fixed word "Anonymous" plus one animal from the pool below,
e.g. "Anonymous Fox". With a 75-animal pool and a static prefix, two people can
occasionally land on the same animal; in a 1:1 chat each person only ever sees
the *other* participant's alias, so a same-animal collision is invisible there.
Across one user's many parallel chats, repeats are possible by the same math and
are accepted as cosmetic.

Aliases are cosmetic only; identity is still governed by ``current_phase``.
"""

from __future__ import annotations

import hashlib

_ANIMALS = (
    "Antelope",
    "Badger",
    "Bear",
    "Beaver",
    "Bison",
    "Bobcat",
    "Buffalo",
    "Caribou",
    "Cheetah",
    "Civet",
    "Cobra",
    "Crane",
    "Deer",
    "Dingo",
    "Dolphin",
    "Eagle",
    "Egret",
    "Elk",
    "Falcon",
    "Ferret",
    "Finch",
    "Fox",
    "Gazelle",
    "Gecko",
    "Gibbon",
    "Hare",
    "Hawk",
    "Heron",
    "Ibex",
    "Jackal",
    "Jaguar",
    "Kestrel",
    "Kite",
    "Koala",
    "Lark",
    "Lemur",
    "Leopard",
    "Lynx",
    "Macaw",
    "Magpie",
    "Marten",
    "Meerkat",
    "Mink",
    "Mongoose",
    "Moose",
    "Narwhal",
    "Newt",
    "Ocelot",
    "Orca",
    "Oryx",
    "Osprey",
    "Otter",
    "Owl",
    "Panda",
    "Panther",
    "Pelican",
    "Penguin",
    "Puffin",
    "Quail",
    "Raccoon",
    "Ram",
    "Reindeer",
    "Robin",
    "Seal",
    "Serval",
    "Sparrow",
    "Starling",
    "Stork",
    "Swan",
    "Tapir",
    "Tiger",
    "Walrus",
    "Weasel",
    "Wolf",
    "Yak",
)


def anonymous_alias(chat_id: str, user_id: str) -> str:
    """Return a stable "Anonymous <Animal>" alias for a user within a chat."""
    digest = hashlib.sha256(f"{chat_id}:{user_id}".encode()).digest()
    animal = _ANIMALS[digest[0] % len(_ANIMALS)]
    return f"Anonymous {animal}"
