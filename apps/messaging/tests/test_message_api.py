"""API tests for the messaging endpoints (storage mocked)."""

from __future__ import annotations

import uuid
from unittest import mock

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from apps.chats.enums import EndReason
from apps.chats.services.chat_service import ChatService
from apps.messaging.enums import MediaStatus, MediaVisibility
from apps.users.models import User

_UPLOAD = "apps.common.services.storage_service.StorageService.upload_fileobj"
_DOWNLOAD = "apps.common.services.storage_service.StorageService.download_bytes"
_DELETE = "apps.common.services.storage_service.StorageService.delete_object"


def _user() -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=f"{uuid.uuid4().hex}@college.edu",
    )


def _client(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


class MessageApiTests(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self.a = _user()
        self.b = _user()
        self.chats = ChatService()
        self.chat = self.chats.create_chat(self.a, self.b).data
        self.client = _client(self.a)

    def _messages_url(self) -> str:
        return f"/api/v1/chats/{self.chat.id}/messages"

    def test_send_and_list(self) -> None:
        send = self.client.post(
            self._messages_url(), {"content": "hello"}, format="json"
        )
        self.assertEqual(send.status_code, 201)
        listing = self.client.get(self._messages_url())
        items = listing.json()["data"]["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["text_content"], "hello")

    def test_non_participant_cannot_send(self) -> None:
        response = _client(_user()).post(
            self._messages_url(), {"content": "hi"}, format="json"
        )
        self.assertEqual(response.status_code, 403)

    def test_read_only_chat_rejects_send(self) -> None:
        self.chats.end_chat(str(self.chat.id), reason=EndReason.USER_EXIT)
        response = self.client.post(
            self._messages_url(), {"content": "hi"}, format="json"
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "CHAT_READ_ONLY")

    def test_too_long_message(self) -> None:
        response = self.client.post(
            self._messages_url(), {"content": "x" * 2001}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "MESSAGE_TOO_LONG")

    def test_send_image_and_view_once_flow(self) -> None:
        image = SimpleUploadedFile("p.jpg", b"data", content_type="image/jpeg")
        with mock.patch(_UPLOAD, side_effect=lambda f, k, content_type=None: k):
            send = self.client.post(
                self._messages_url() + "/image",
                {"file": image, "media_visibility": MediaVisibility.VIEW_ONCE},
                format="multipart",
            )
        self.assertEqual(send.status_code, 201)
        body = send.json()["data"]
        message_id = body["id"]
        # VIEW_ONCE never ships a URL; a pending flag tells the client to show the bubble.
        self.assertIsNone(body["media_url"])
        self.assertTrue(body["media_pending"])

        # Recipient consumes it once → raw image bytes (not JSON), blob deleted.
        with mock.patch(_DOWNLOAD, return_value=(b"rawbytes", "image/jpeg")), mock.patch(
            _DELETE
        ) as delete_obj:
            viewed = _client(self.b).post(f"/api/v1/messages/{message_id}/view")
        self.assertEqual(viewed.status_code, 200)
        self.assertEqual(viewed["Content-Type"], "image/jpeg")
        self.assertEqual(viewed.content, b"rawbytes")
        delete_obj.assert_called_once()

        # Second view is no longer available → 410 GONE.
        with mock.patch(_DOWNLOAD, return_value=(b"rawbytes", "image/jpeg")):
            again = _client(self.b).post(f"/api/v1/messages/{message_id}/view")
        self.assertEqual(again.status_code, 410)

    def test_delete_own_message(self) -> None:
        send = self.client.post(
            self._messages_url(), {"content": "mine"}, format="json"
        )
        message_id = send.json()["data"]["id"]
        response = self.client.delete(f"/api/v1/messages/{message_id}")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["data"]["is_deleted"])

    def test_cannot_delete_others_message(self) -> None:
        send = self.client.post(
            self._messages_url(), {"content": "mine"}, format="json"
        )
        message_id = send.json()["data"]["id"]
        response = _client(self.b).delete(f"/api/v1/messages/{message_id}")
        self.assertEqual(response.status_code, 403)
