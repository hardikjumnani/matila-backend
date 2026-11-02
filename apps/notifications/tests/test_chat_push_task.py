"""Tests for the push_chat_event task (FCM + cache mocked/real locmem)."""

from __future__ import annotations

import uuid
from unittest import mock

from django.core.cache import cache
from django.test import TestCase

from apps.common.firebase import PushResult
from apps.common.realtime import chat_presence_key
from apps.configuration.constants import FeatureFlagKey
from apps.configuration.services.configuration_service import ConfigurationService
from apps.notifications.enums import DevicePlatform
from apps.notifications.models import DeviceToken
from apps.notifications.tasks.chat_push import push_chat_event
from apps.users.models import User

_SEND = "apps.common.firebase.send_push"


def _ok(n=1):
    return PushResult(success_count=n, failure_count=0, invalid_tokens=[])


class PushChatEventTests(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self.user = User.objects.create(
            firebase_uid="fb_" + uuid.uuid4().hex,
            college_email=f"{uuid.uuid4().hex}@college.edu",
        )
        self.chat_id = str(uuid.uuid4())
        self.data = {"type": "chat.message", "chat_id": self.chat_id}

    def _token(self, token="tok-1"):
        return DeviceToken.objects.create(
            user=self.user, token=token, device_id="dev-1", platform=DevicePlatform.IOS
        )

    def _run(self, kind="message"):
        push_chat_event(
            str(self.user.id), kind, self.chat_id, "Azure Seal", "You got a message",
            self.data,
        )

    def test_successful_delivery_with_collapse_key(self):
        self._token()
        with mock.patch(_SEND, return_value=_ok()) as send:
            self._run()
        send.assert_called_once()
        self.assertEqual(send.call_args.kwargs["collapse_key"], f"chat-{self.chat_id}")

    def test_no_tokens_no_send(self):
        with mock.patch(_SEND) as send:
            self._run()
        send.assert_not_called()

    def test_flag_off_no_send(self):
        self._token()
        ConfigurationService().set_flag(
            key=FeatureFlagKey.CHAT_PUSH_ENABLED, value=False
        )
        with mock.patch(_SEND) as send:
            self._run()
        send.assert_not_called()

    def test_reaction_flag_off_no_send_but_message_still_sends(self):
        self._token()
        ConfigurationService().set_flag(
            key=FeatureFlagKey.CHAT_REACTION_PUSH_ENABLED, value=False
        )
        with mock.patch(_SEND, return_value=_ok()) as send:
            self._run(kind="reaction")
            send.assert_not_called()
            self._run(kind="message")
            send.assert_called_once()

    def test_presence_suppression(self):
        self._token()
        cache.set(chat_presence_key(self.chat_id, str(self.user.id)), "1", 60)
        with mock.patch(_SEND) as send:
            self._run()
        send.assert_not_called()

    def test_cooldown_coalesces_second_push(self):
        self._token()
        with mock.patch(_SEND, return_value=_ok()) as send:
            self._run()
            self._run()  # within cooldown -> skipped
        send.assert_called_once()

    def test_dead_token_deactivated(self):
        self._token("dead")
        with mock.patch(
            _SEND,
            return_value=PushResult(success_count=0, failure_count=1,
                                    invalid_tokens=["dead"]),
        ):
            self._run()
        self.assertFalse(DeviceToken.objects.get(token="dead").is_active)
