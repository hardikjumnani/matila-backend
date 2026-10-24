"""Per-user match block list (BlockedName) management."""

from __future__ import annotations

from django.db import transaction

from apps.users.constants import MAX_BLOCK_NAME_LEN, MAX_BLOCK_NAMES
from apps.users.models import BlockedName, User
from apps.users.name_match import normalize_name


class BlockListService:
    def set_names(self, user: User, raw_names: list[str]) -> list[BlockedName]:
        """Replace the user's block list with ``raw_names`` (full-list replace).

        Trims each, drops blanks, caps length, de-duplicates by normalized form,
        and caps the count. Idempotent.
        """
        seen: set[str] = set()
        rows: list[BlockedName] = []
        for raw in raw_names or []:
            name = (raw or "").strip()[:MAX_BLOCK_NAME_LEN]
            if not name:
                continue
            norm = normalize_name(name)
            if not norm or norm in seen:
                continue
            seen.add(norm)
            rows.append(BlockedName(user=user, name=name, name_normalized=norm))
            if len(rows) >= MAX_BLOCK_NAMES:
                break
        with transaction.atomic():
            BlockedName.objects.filter(user=user).delete()
            BlockedName.objects.bulk_create(rows)
        return rows

    def names_for(self, user: User) -> list[str]:
        """The user's block list as raw display strings (A-Z)."""
        return list(
            BlockedName.objects.filter(user=user)
            .order_by("name")
            .values_list("name", flat=True)
        )
