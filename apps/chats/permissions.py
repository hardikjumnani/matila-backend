"""
Chat-scoped permission.

Guards endpoints whose URL carries a ``chat_id`` so only participants may access
that chat's resources. Message-scoped endpoints (``/messages/{id}/...``) rely on
the service's participant/sender checks instead, since the chat is not in the
URL.
"""

from __future__ import annotations

from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from apps.chats.models import Chat, ChatParticipant


class IsChatParticipant(BasePermission):
    """Allow only participants of the chat identified by ``chat_id`` in the URL."""

    message = "You are not a participant of this chat."

    def has_permission(self, request: Request, view: APIView) -> bool:
        chat_id = view.kwargs.get("chat_id")
        if not chat_id:
            return True  # No chat in scope; nothing to guard here.
        # If the chat does not exist, defer to the view so it can return 404
        # rather than leaking existence via a 403.
        if not Chat.objects.filter(id=chat_id).exists():
            return True
        return ChatParticipant.objects.filter(
            chat_id=chat_id, user=request.user
        ).exists()
