"""Orchestration tests for SuspicionService (DB; config stubbed)."""

from __future__ import annotations

import uuid
from unittest import mock

from django.test import TestCase

from apps.chats.models import Chat
from apps.configuration.constants import AppConfigKey, FeatureFlagKey
from apps.privacy.enums import SuspicionReviewStatus
from apps.privacy.models import SuspicionEvent, UserSuspicionProfile
from apps.privacy.services.suspicion_service import SuspicionService


class _StubConfig:
    def __init__(self, *, enabled=True, min_record=2, attention=8):
        self.enabled = enabled
        self.min_record = min_record
        self.attention = attention

    def is_feature_enabled(self, key):
        return self.enabled if key == FeatureFlagKey.SUSPICION_ENABLED else False

    def get_config(self, key, default=None):
        return {
            AppConfigKey.SUSPICION_SIGNAL_WEIGHTS: None,  # fall back to defaults
            AppConfigKey.SUSPICION_MIN_RECORD_WEIGHT: self.min_record,
            AppConfigKey.SUSPICION_ATTENTION_SCORE: self.attention,
        }.get(key, default)


def _user():
    from apps.users.models import User

    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=f"{uuid.uuid4().hex}@college.edu",
        full_name="Test User",
    )


class SuspicionServiceTests(TestCase):
    def setUp(self) -> None:
        self.chat = Chat.objects.create()
        self.user = _user()

    def _svc(self, **cfg):
        return SuspicionService(
            configuration_service=_StubConfig(**cfg),
            audit_service=mock.MagicMock(),
        )

    def test_records_event_and_profile_when_enabled(self):
        self._svc().inspect(chat=self.chat, sender=self.user, text="ping me on insta")
        event = SuspicionEvent.objects.get(user=self.user)
        self.assertIn(event.top_signal, {"BRAND_MENTION", "CONTACT_SOFT"})
        self.assertGreaterEqual(event.score, 2)
        profile = UserSuspicionProfile.objects.get(user=self.user)
        self.assertEqual(profile.event_count, 1)
        self.assertEqual(profile.score, event.score)
        self.assertGreater(profile.priority_score, 0)

    def test_ambient_only_contributes_zero_priority(self):
        # Romanized Hindi records (ambient) but must not rank the user: priority 0,
        # tier CLEAN, and no attention audit even at a low threshold.
        svc = self._svc(min_record=1, attention=1)
        svc.inspect(chat=self.chat, sender=self.user, text="chalo yaar kaise ho bhai")
        profile = UserSuspicionProfile.objects.get(user=self.user)
        self.assertGreater(profile.score, 0)
        self.assertEqual(profile.priority_score, 0)
        self.assertEqual(profile.tier, "CLEAN")
        self.assertFalse(svc._audit_service.log.called)

    def test_blocked_leak_recorded_as_signal(self):
        svc = self._svc()
        svc.inspect(
            chat=self.chat, sender=self.user, text="9876543210",
            leak_blocked=True, leak_category="PHONE",
        )
        event = SuspicionEvent.objects.get(user=self.user)
        signals = {s["signal"] for s in event.signals}
        self.assertIn("BLOCKED_LEAK", signals)
        profile = UserSuspicionProfile.objects.get(user=self.user)
        self.assertGreaterEqual(profile.priority_score, 5)

    def test_disabled_records_nothing(self):
        self._svc(enabled=False).inspect(
            chat=self.chat, sender=self.user, text="ping me on insta"
        )
        self.assertFalse(SuspicionEvent.objects.filter(user=self.user).exists())

    def test_below_min_record_is_skipped(self):
        # Benign text scores 0, under the min-record floor -> no row.
        self._svc().inspect(
            chat=self.chat, sender=self.user, text="see you at the library"
        )
        self.assertFalse(SuspicionEvent.objects.filter(user=self.user).exists())
        self.assertFalse(UserSuspicionProfile.objects.filter(user=self.user).exists())

    def test_attention_threshold_audits(self):
        svc = self._svc(attention=3)
        audit = svc._audit_service
        svc.inspect(chat=self.chat, sender=self.user, text="ping me on insta")  # score 3
        self.assertTrue(audit.log.called)

    def test_cleared_profile_reopens_on_new_signal(self):
        UserSuspicionProfile.objects.create(
            user=self.user, review_status=SuspicionReviewStatus.CLEARED.value
        )
        self._svc().inspect(chat=self.chat, sender=self.user, text="my id 9876543")
        profile = UserSuspicionProfile.objects.get(user=self.user)
        self.assertEqual(profile.review_status, SuspicionReviewStatus.UNREVIEWED.value)

    def test_never_blocks_message_path(self):
        # inspect returns None regardless (non-blocking contract).
        self.assertIsNone(
            self._svc().inspect(chat=self.chat, sender=self.user, text="asdfghjkl")
        )
