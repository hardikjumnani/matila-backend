"""Tests for the deterministic anonymous alias ("Anonymous <Animal>")."""

from __future__ import annotations

import uuid

from apps.chats.aliases import _ANIMALS, anonymous_alias


def test_pool_is_75_unique_animals() -> None:
    assert len(_ANIMALS) == 75
    assert len(set(_ANIMALS)) == 75  # no duplicates


def test_alias_format_is_anonymous_plus_pool_animal() -> None:
    alias = anonymous_alias(str(uuid.uuid4()), str(uuid.uuid4()))
    prefix, _, animal = alias.partition(" ")
    assert prefix == "Anonymous"          # capital A, single space
    assert alias == f"Anonymous {animal}"
    assert animal in _ANIMALS


def test_alias_is_deterministic() -> None:
    chat_id, user_id = str(uuid.uuid4()), str(uuid.uuid4())
    assert anonymous_alias(chat_id, user_id) == anonymous_alias(chat_id, user_id)


def test_alias_varies_by_user_and_chat() -> None:
    # Not guaranteed distinct (75-animal pool), but the mapping must at least
    # respond to both inputs across a spread of values.
    seen = {
        anonymous_alias(str(c), str(u))
        for c in range(40)
        for u in range(40)
    }
    assert len(seen) > 1
