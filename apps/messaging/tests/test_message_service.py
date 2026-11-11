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
from apps.messaging.models import Message
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

    # -- Idempotent sends (client_message_id dedup) -------------------------

    def test_duplicate_client_message_id_dedups_text(self) -> None:
        with mock.patch.object(self.service, "_broadcast_new_message") as bcast:
            first = self.service.send_text(
                chat_id=str(self.chat.id),
                sender=self.a,
                content="hi",
                client_message_id="local_1_0",
            )
            second = self.service.send_text(
                chat_id=str(self.chat.id),
                sender=self.a,
                content="hi",
                client_message_id="local_1_0",
            )
        self.assertTrue(first.success and second.success)
        self.assertEqual(first.data.id, second.data.id)
        # Exactly one row and one broadcast; the retry was a no-op.
        self.assertEqual(
            Message.objects.filter(chat=self.chat, sender=self.a).count(), 1
        )
        self.assertEqual(bcast.call_count, 1)
        self.chat.refresh_from_db()
        self.assertEqual(self.chat.message_count, 1)

    def test_blank_client_message_id_never_dedups(self) -> None:
        self.service.send_text(chat_id=str(self.chat.id), sender=self.a, content="a")
        self.service.send_text(chat_id=str(self.chat.id), sender=self.a, content="b")
        self.assertEqual(
            Message.objects.filter(chat=self.chat, sender=self.a).count(), 2
        )

    def test_same_client_message_id_different_senders_are_distinct(self) -> None:
        first = self.service.send_text(
            chat_id=str(self.chat.id), sender=self.a, content="hi",
            client_message_id="dup",
        )
        second = self.service.send_text(
            chat_id=str(self.chat.id), sender=self.b, content="hi",
            client_message_id="dup",
        )
        self.assertNotEqual(first.data.id, second.data.id)
        self.assertEqual(Message.objects.filter(chat=self.chat).count(), 2)

    def test_dedup_returns_existing_even_after_chat_closed(self) -> None:
        sent = self.service.send_text(
            chat_id=str(self.chat.id), sender=self.a, content="hi",
            client_message_id="k",
        )
        self.chats.end_chat(str(self.chat.id), reason=EndReason.USER_EXIT)
        # A lost-ack retry after the chat went read-only still returns the
        # original message, not CHAT_READ_ONLY.
        retry = self.service.send_text(
            chat_id=str(self.chat.id), sender=self.a, content="hi",
            client_message_id="k",
        )
        self.assertTrue(retry.success)
        self.assertEqual(retry.data.id, sent.data.id)

    def test_concurrent_race_falls_back_to_existing_text(self) -> None:
        # Simulate the true race: the pre-lookup misses (returns None) but a row
        # with the same key already exists, so create() hits the unique constraint
        # and the IntegrityError handler re-fetches and returns the winner.
        winner = self.service.send_text(
            chat_id=str(self.chat.id), sender=self.a, content="hi",
            client_message_id="race",
        ).data
        with mock.patch.object(
            self.service, "_find_by_client_message_id", side_effect=[None, winner]
        ), mock.patch.object(self.service, "_broadcast_new_message") as bcast:
            result = self.service.send_text(
                chat_id=str(self.chat.id), sender=self.a, content="hi",
                client_message_id="race",
            )
        self.assertTrue(result.success)
        self.assertEqual(result.data.id, winner.id)
        self.assertEqual(bcast.call_count, 0)
        self.assertEqual(
            Message.objects.filter(chat=self.chat, sender=self.a).count(), 1
        )

    def test_duplicate_client_message_id_dedups_image_no_reupload(self) -> None:
        kwargs = dict(
            chat_id=str(self.chat.id),
            sender=self.a,
            filename="p.jpg",
            content_type="image/jpeg",
            client_message_id="img_1",
        )
        first = self.service.send_image(fileobj=io.BytesIO(b"x"), **kwargs)
        second = self.service.send_image(fileobj=io.BytesIO(b"x"), **kwargs)
        self.assertTrue(first.success and second.success)
        self.assertEqual(first.data.id, second.data.id)
        # The blob is uploaded once; the retry never touches storage.
        self.assertEqual(self.storage.upload_fileobj.call_count, 1)
        self.assertEqual(
            Message.objects.filter(
                chat=self.chat, sender=self.a, message_type=MessageType.IMAGE
            ).count(),
            1,
        )

    def test_concurrent_race_deletes_orphan_image_blob(self) -> None:
        winner = self.service.send_image(
            chat_id=str(self.chat.id), sender=self.a, fileobj=io.BytesIO(b"x"),
            filename="p.jpg", content_type="image/jpeg", client_message_id="img_race",
        ).data
        with mock.patch.object(
            self.service, "_find_by_client_message_id", side_effect=[None, winner]
        ):
            result = self.service.send_image(
                chat_id=str(self.chat.id), sender=self.a, fileobj=io.BytesIO(b"x"),
                filename="p.jpg", content_type="image/jpeg",
                client_message_id="img_race",
            )
        self.assertTrue(result.success)
        self.assertEqual(result.data.id, winner.id)
        # The orphaned (just-uploaded) blob is cleaned up.
        self.storage.delete_object.assert_called_once()
