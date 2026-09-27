"""
Serializers for the chats API.

Identity masking is enforced here: the other participant's name and photo are
exposed only once the chat's phase is REVEALED. Because ``current_phase`` becomes
REVEALED on reveal and stays REVEALED thereafter (even for chats that later end),
this single predicate correctly implements the frozen "identity visible" rules.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.chats.aliases import anonymous_alias
from apps.chats.enums import ChatPhase, ChatStatus
from apps.common.media import resolve_media_url

_WRITABLE = (ChatStatus.ACTIVE, ChatStatus.EXTENDED, ChatStatus.REVEALED)


class ChatSerializer(serializers.Serializer):
    """Read representation of a chat for its participant."""

    id = serializers.UUIDField()
    status = serializers.CharField()
    current_phase = serializers.CharField()
    message_count = serializers.IntegerField()
    last_message_at = serializers.DateTimeField(allow_null=True)
    current_phase_ends_at = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField()
    ended_at = serializers.DateTimeField(allow_null=True)
    end_reason = serializers.CharField(allow_blank=True)
    identity_visible = serializers.SerializerMethodField()
    is_writable = serializers.SerializerMethodField()
    other_participant = serializers.SerializerMethodField()
    my_participation = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()

    def _me(self):
        return self.context["request"].user

    def get_identity_visible(self, obj) -> bool:
        return obj.current_phase == ChatPhase.REVEALED

    def get_is_writable(self, obj) -> bool:
        return obj.status in _WRITABLE

    def get_other_participant(self, obj) -> dict | None:
        me = self._me()
        others = [p for p in obj.participants.all() if p.user_id != me.id]
        if not others:
            return None
        participant = others[0]
        visible = obj.current_phase == ChatPhase.REVEALED
        # Partial unmask: during an active Safe Reveal decision the boy is shown
        # to the reviewing girl only (she is FEMALE, he is MALE, and the round is
        # in SAFE_DECISION with the boy already revealed).
        if not visible:
            from apps.reveal.enums import DecisionRoundPhase
            from apps.reveal.models import DecisionRound
            from apps.users.enums import Gender

            if me.gender == Gender.FEMALE and participant.user.gender == Gender.MALE:
                visible = DecisionRound.objects.filter(
                    chat_id=obj.id,
                    phase=DecisionRoundPhase.SAFE_DECISION,
                    boy_revealed_to_girl_at__isnull=False,
                ).exists()
        # A stable anonymous alias so the client always has a label; the real
        # name is exposed only once identity is visible. Gender is always exposed
        # (it drives the blue/pink anonymous avatar and is not identity). The read
        # pointer is exposed regardless of phase (it is a message id, not
        # identity) so read receipts persist across refetch/restart.
        return {
            "user_id": str(participant.user_id),
            "alias": anonymous_alias(str(obj.id), str(participant.user_id)),
            "gender": participant.user.gender,
            "display_name": participant.user.full_name if visible else None,
            "profile_photo_url": (
                resolve_media_url(participant.user.profile_photo_url)
                if visible
                else None
            ),
            "last_read_message_id": (
                str(participant.last_read_message_id)
                if participant.last_read_message_id
                else None
            ),
            "last_read_at": participant.last_read_at,
        }

    def get_unread_count(self, obj) -> int:
        """Messages from the other participant after this user's read pointer."""
        from apps.messaging.enums import MessageType
        from apps.messaging.models import Message

        me = self._me()
        mine = [p for p in obj.participants.all() if p.user_id == me.id]
        if not mine:
            return 0
        queryset = (
            Message.objects.filter(chat_id=obj.id, is_deleted=False)
            .exclude(sender_id=me.id)
            .exclude(message_type=MessageType.SYSTEM)
        )
        if mine[0].last_read_at is not None:
            queryset = queryset.filter(created_at__gt=mine[0].last_read_at)
        return queryset.count()

    def get_my_participation(self, obj) -> dict | None:
        me = self._me()
        mine = [p for p in obj.participants.all() if p.user_id == me.id]
        if not mine:
            return None
        participant = mine[0]
        return {
            "status": participant.status,
            "is_hidden": participant.is_chat_hidden,
            "last_read_message_id": (
                str(participant.last_read_message_id)
                if participant.last_read_message_id
                else None
            ),
            "last_read_at": participant.last_read_at,
        }


class ChatReadRequestSerializer(serializers.Serializer):
    """Body for POST /chats/{id}/read."""

    last_read_message_id = serializers.UUIDField()
