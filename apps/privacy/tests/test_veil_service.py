"""Orchestration tests for VeilService (DB + cache; config stubbed)."""

from __future__ import annotations

import uuid
from unittest import mock

from django.core.cache import cache
from django.test import TestCase

from apps.chats.models import Chat
from apps.configuration.constants import AppConfigKey, FeatureFlagKey
from apps.privacy.enums import LeakAction, VeilMode
from apps.privacy.models import LeakEvent, LeakStrike
from apps.privacy.services.veil_service import VeilService
from apps.users.models import User


class _StubConfig:
    """Minimal ConfigurationService stand-in to control mode/flag in tests."""

    def __init__(self, *, enabled=True, mode=VeilMode.ENFORCE.value, window=120, threshold=5):
        self.enabled = enabled
        self.mode = mode
        self.window = window
        self.threshold = threshold

    def is_feature_enabled(self, key):
        return self.enabled

    def get_config(self, key, default=None):
        return {
            AppConfigKey.VEIL_MODE: self.mode,
            AppConfigKey.VEIL_WINDOW_SECONDS: self.window,
            AppConfigKey.VEIL_ESCALATE_THRESHOLD: self.threshold,
        }.get(key, default)


def _user() -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=f"{uuid.uuid4().hex}@college.edu",
    )


class VeilServiceTests(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self.chat = Chat.objects.create()
        self.user = _user()

    def _svc(self, **cfg):
        return VeilService(
            configuration_service=_StubConfig(**cfg),
            notification_service=mock.MagicMock(),
            audit_service=mock.MagicMock(),
        )

    def test_blocks_phone_and_records_raw(self):
        svc = self._svc()
        d = svc.inspect_text(chat=self.chat, sender=self.user, text="9876543210")
        self.assertTrue(d.blocked)
        self.assertTrue(d.user_message)
        event = LeakEvent.objects.get(user=self.user)
        self.assertEqual(event.action, LeakAction.BLOCK.value)
        self.assertIn("9876543210", event.raw_message)  # temporary raw logging
        self.assertEqual(LeakStrike.objects.get(user=self.user).count, 1)

    def test_benign_passes_without_event(self):
        svc = self._svc()
        d = svc.inspect_text(chat=self.chat, sender=self.user, text="hey how are you")
        self.assertFalse(d.blocked)
        self.assertFalse(LeakEvent.objects.filter(user=self.user).exists())

    def test_cross_message_reassembly_blocks_second(self):
        svc = self._svc()
        d1 = svc.inspect_text(
            chat=self.chat, sender=self.user, text="my number is nine eight seven six"
        )
        self.assertFalse(d1.blocked)
        d2 = svc.inspect_text(
            chat=self.chat, sender=self.user, text="five four three two one zero"
        )
        self.assertTrue(d2.blocked)

    def test_shadow_mode_allows_but_records(self):
        svc = self._svc(mode=VeilMode.SHADOW.value)
        d = svc.inspect_text(chat=self.chat, sender=self.user, text="9876543210")
        self.assertFalse(d.blocked)  # shadow: logged, not blocked
        event = LeakEvent.objects.get(user=self.user)
        self.assertEqual(event.mode, VeilMode.SHADOW.value)
        # Strikes are not counted in shadow mode.
        self.assertFalse(LeakStrike.objects.filter(user=self.user).exists())

    def test_disabled_flag_is_noop(self):
        svc = self._svc(enabled=False)
        d = svc.inspect_text(chat=self.chat, sender=self.user, text="9876543210")
        self.assertFalse(d.blocked)
        self.assertFalse(LeakEvent.objects.filter(user=self.user).exists())

    def test_escalation_after_threshold(self):
        audit = mock.MagicMock()
        svc = VeilService(
            configuration_service=_StubConfig(threshold=2),
            notification_service=mock.MagicMock(),
            audit_service=audit,
        )
        first = svc.inspect_text(chat=self.chat, sender=self.user, text="9876543210")
        second = svc.inspect_text(chat=self.chat, sender=self.user, text="9876543210")
        self.assertEqual(first.action, LeakAction.BLOCK.value)
        self.assertEqual(second.action, LeakAction.ESCALATE.value)
        audit.log.assert_called_once()
        self.assertEqual(audit.log.call_args.kwargs["action"], "veil.escalated")

    def test_tone_graduates(self):
        svc = self._svc()
        m1 = svc.inspect_text(chat=self.chat, sender=self.user, text="9876543210").user_message
        m2 = svc.inspect_text(chat=self.chat, sender=self.user, text="9876543210").user_message
        self.assertNotEqual(m1, m2)  # gentle -> firm
