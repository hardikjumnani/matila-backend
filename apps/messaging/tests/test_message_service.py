"""Tests for MessageService (storage mocked; real chat/config services)."""

from __future__ import annotations

import io
import uuid
from unittest import mock

from django.core.cache import cache
from django.test import TestCase

from apps.chats.enums import EndReason
from apps.chats.services.chat_service import ChatService
from apps.common.services.storage_service import StorageService
from apps.configuration.constants import FeatureFlagKey
from apps.configuration.models import FeatureFlag
from apps.configuration.services.configuration_service import ConfigurationService
from apps.messaging.enums import MediaStatus, MediaVisibility, MessageType
from apps.messaging.services.message_service import MessageService
from apps.users.models import User


def _user() -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=f"{uuid.uuid4().hex}@college.edu",
    )


class MessageServiceTests(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self.chats = ChatService(notification_service=mock.MagicMock())
        self.storage = mock.MagicMock()
        self.storage.build_key.side_effect = StorageService.build_key
        self.storage.upload_fileobj.side_effect = (
            lambda fileobj, key, content_type=None: key
        )
        self.storage.download_bytes.return_value = (b"imgbytes", "image/jpeg")
        self.service = MessageService(
            chat_service=self.chats,
            storage_service=self.storage,
            configuration_service=ConfigurationService(),
        )
        self.a = _user()
        self.b = _user()
        self.chat = self.chats.create_chat(self.a, self.b).data

    def _send(self, content="hi"):
        return self.service.send_text(
            chat_id=str(self.chat.id), sender=self.a, content=content
        )

    def test_send_text_creates_message_and_counts(self) -> None:
        result = self._send("hello")
        self.assertTrue(result.success)
        self.chat.refresh_from_db()
        self.assertEqual(self.chat.message_count, 1)
        self.assertIsNotNone(self.chat.last_message_at)

    def test_empty_message_rejected(self) -> None:
        self.assertEqual(self._send("   ").error_code, "VALIDATION_ERROR")

    def test_too_long_message_rejected(self) -> None:
        self.assertEqual(self._send("x" * 2001).error_code, "MESSAGE_TOO_LONG")

    def test_non_participant_forbidden(self) -> None:
        result = self.service.send_text(
            chat_id=str(self.chat.id), sender=_user(), content="hi"
        )
        self.assertEqual(result.error_code, "FORBIDDEN")

    def test_read_only_chat_rejected(self) -> None:
        self.chats.end_chat(str(self.chat.id), reason=EndReason.USER_EXIT)
        self.assertEqual(self._send("hi").error_code, "CHAT_READ_ONLY")

    def test_reply_to_valid_and_invalid(self) -> None:
        original = self._send("first").data
        ok = self.service.send_text(
            chat_id=str(self.chat.id),
            sender=self.b,
            content="reply",
            reply_to_message_id=str(original.id),
        )
        self.assertTrue(ok.success)
        self.assertEqual(ok.data.reply_to_message_id, original.id)
        bad = self.service.send_text(
            chat_id=str(self.chat.id),
            sender=self.b,
            content="reply",
            reply_to_message_id=str(uuid.uuid4()),
        )
        self.assertEqual(bad.error_code, "INVALID_REPLY_TARGET")

    def test_send_image_sets_media_fields(self) -> None:
        result = self.service.send_image(
            chat_id=str(self.chat.id),
            sender=self.a,
            fileobj=io.BytesIO(b"x"),
            filename="p.jpg",
            content_type="image/jpeg",
            visibility=MediaVisibility.VIEW_ONCE,
        )
        self.assertTrue(result.success)
        self.assertEqual(result.data.message_type, MessageType.IMAGE)
        self.assertEqual(result.data.media_status, MediaStatus.AVAILABLE)
        self.assertIsNotNone(result.data.media_expires_at)

    def test_send_image_disabled_flag(self) -> None:
        FeatureFlag.objects.create(
            key=FeatureFlagKey.IMAGE_MESSAGES_ENABLED, value=False
        )
        cache.clear()
        result = self.service.send_image(
            chat_id=str(self.chat.id),
            sender=self.a,
            fileobj=io.BytesIO(b"x"),
            filename="p.jpg",
            content_type="image/jpeg",
        )
        self.assertEqual(result.error_code, "FORBIDDEN")

    def test_view_once_lifecycle(self) -> None:
        image = self.service.send_image(
            chat_id=str(self.chat.id),
            sender=self.a,
            fileobj=io.BytesIO(b"x"),
            filename="p.jpg",
            content_type="image/jpeg",
            visibility=MediaVisibility.VIEW_ONCE,
        ).data
        # Recipient consumes it exactly once: gets the bytes back, blob destroyed.
        viewed = self.service.view_once(message_id=str(image.id), user=self.b)
        self.assertTrue(viewed.success)
        data, content_type = viewed.data
        self.assertEqual(data, b"imgbytes")
        image.refresh_from_db()
        self.assertEqual(image.media_status, MediaStatus.VIEWED)
        self.storage.delete_object.assert_called_once()
        # Second view is no longer available.
        again = self.service.view_once(message_id=str(image.id), user=self.b)
        self.assertEqual(again.error_code, "MEDIA_NOT_AVAILABLE")

    def test_sender_cannot_consume_own_view_once(self) -> None:
        image = self.service.send_image(
            chat_id=str(self.chat.id),
            sender=self.a,
            fileobj=io.BytesIO(b"x"),
            filename="p.jpg",
            content_type="image/jpeg",
            visibility=MediaVisibility.VIEW_ONCE,
        ).data
        self.assertEqual(
            self.service.view_once(message_id=str(image.id), user=self.a).error_code,
            "FORBIDDEN",
        )

    def test_soft_delete_only_by_sender(self) -> None:
        message = self._send("mine").data
        self.assertEqual(
            self.service.soft_delete(
                message_id=str(message.id), user=self.b
            ).error_code,
            "FORBIDDEN",
        )
        deleted = self.service.soft_delete(message_id=str(message.id), user=self.a)
        self.assertTrue(deleted.data.is_deleted)

    def test_system_message_does_not_count(self) -> None:
        self.service.create_system_message(chat=self.chat, content="System notice")
        self.chat.refresh_from_db()
        self.assertEqual(self.chat.message_count, 0)
