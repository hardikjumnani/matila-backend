"""Backfill Chat.matched_intent for chats created before the field existed.

Matching is same-intent, so a chat's intent equals either participant's intent.
We read a participant's CURRENT user.intent (best available signal; queue entries
are deleted on match). Chats left empty (no participant / blank intent) are treated
as RELATIONSHIP by the exclusivity check, so leaving them empty is safe.
"""

from __future__ import annotations

from django.db import migrations


def backfill(apps, schema_editor):
    Chat = apps.get_model("chats", "Chat")
    ChatParticipant = apps.get_model("chats", "ChatParticipant")
    for chat in Chat.objects.filter(matched_intent=""):
        participant = (
            ChatParticipant.objects.filter(chat=chat)
            .select_related("user")
            .first()
        )
        intent = getattr(getattr(participant, "user", None), "intent", "") or ""
        if intent:
            chat.matched_intent = intent
            chat.save(update_fields=["matched_intent"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("chats", "0003_chat_matched_intent"),
    ]

    operations = [
        migrations.RunPython(backfill, noop),
    ]
