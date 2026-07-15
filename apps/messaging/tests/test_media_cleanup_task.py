"""Tests for the cleanup_expired_media scheduled task (S3 mocked)."""

from __future__ import annotations

import uuid
from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.chats.services.chat_service import ChatService
from apps.messaging.enums import MediaStatus, MediaVisibility, MessageType
from apps.messaging.models import Message
from apps.messaging.tasks.media_cleanup import cleanup_expired_media
from apps.users.models import User

_DELETE = "apps.common.services.storage_service.StorageService.delete_object"


def _user() -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=f"{uuid.uuid4().hex}@college.edu",
    )


class CleanupExpiredMediaTests(TestCase):
    def setUp(self) -> None:
        self.a = _user()
        self.b = _user()
        self.chat = ChatService().create_chat(self.a, self.b).data

    def _image(self, *, status, expires_at=None, visibility=MediaVisibility.NORMAL):
        return Message.objects.create(
            chat=self.chat,
            sender=self.a,
            message_type=MessageType.IMAGE,
            media_url=f"chat/{uuid.uuid4().hex}.jpg",
            media_visibility=visibility,
            media_status=status,
            media_expires_at=expires_at,
        )

    def test_deletes_expired_and_viewed_media(self) -> None:
        expired = self._image(
            status=MediaStatus.AVAILABLE,
            expires_at=timezone.now() - timedelta(days=1),
        )
        viewed = self._image(
            status=MediaStatus.VIEWED, visibility=MediaVisibility.VIEW_ONCE
        )
        fresh = self._image(
            status=MediaStatus.AVAILABLE,
            expires_at=timezone.now() + timedelta(days=1),
        )

        with mock.patch(_DELETE) as delete_object:
            count = cleanup_expired_media()

        self.assertEqual(count, 2)
        self.assertEqual(delete_object.call_count, 2)
        expired.refresh_from_db()
        viewed.refresh_from_db()
        fresh.refresh_from_db()
        self.assertEqual(expired.media_status, MediaStatus.DELETED)
        self.assertEqual(viewed.media_status, MediaStatus.DELETED)
        self.assertEqual(fresh.media_status, MediaStatus.AVAILABLE)
