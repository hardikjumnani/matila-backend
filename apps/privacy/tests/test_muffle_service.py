"""Orchestration tests for MuffleService (DB; config stubbed)."""

from __future__ import annotations

import uuid

from django.test import TestCase

from apps.chats.models import Chat
from apps.configuration.constants import AppConfigKey
from apps.privacy.enums import MuffleMode, ProfanityTier
from apps.privacy.models import LeakStrike, ProfanityEvent
from apps.privacy.services.muffle_service import MuffleService
from apps.users.models import User


class _StubConfig:
    def __init__(self, *, enabled=True, mode=MuffleMode.MASK.value):
        self.enabled = enabled
        self.mode = mode

    def is_feature_enabled(self, key):
        return self.enabled

    def get_config(self, key, default=None):
        return {AppConfigKey.MUFFLE_MODE: self.mode}.get(key, default)


def _user() -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=f"{uuid.uuid4().hex}@college.edu",
    )


class MuffleServiceTests(TestCase):
    def setUp(self) -> None:
        self.chat = Chat.objects.create()
        self.user = _user()

    def _svc(self, **cfg):
        return MuffleService(configuration_service=_StubConfig(**cfg))

    def test_masks_harsh_and_records_raw(self):
        out = self._svc().inspect_and_mask(
            chat=self.chat, sender=self.user, text="you motherfucker"
        )
        self.assertTrue(out.changed)
        self.assertIn("*", out.text)
        self.assertNotIn("motherfucker", out.text)
        ev = ProfanityEvent.objects.get(user=self.user)
        self.assertEqual(ev.tier, ProfanityTier.T1_HARSH.value)
        self.assertIn("motherfucker", ev.raw_message)  # temporary raw logging
        self.assertIn("*", ev.masked_message)

    def test_casual_is_noop(self):
        out = self._svc().inspect_and_mask(
            chat=self.chat, sender=self.user, text="this is fucking great"
        )
        self.assertFalse(out.changed)
        self.assertEqual(out.text, "this is fucking great")
        self.assertFalse(ProfanityEvent.objects.filter(user=self.user).exists())

    def test_shadow_mode_logs_but_does_not_mask(self):
        out = self._svc(mode=MuffleMode.SHADOW.value).inspect_and_mask(
            chat=self.chat, sender=self.user, text="you motherfucker"
        )
        self.assertFalse(out.changed)
        self.assertEqual(out.text, "you motherfucker")  # unchanged in shadow
        ev = ProfanityEvent.objects.get(user=self.user)
        self.assertEqual(ev.mode, MuffleMode.SHADOW.value)

    def test_slur_flags_strike(self):
        out = self._svc().inspect_and_mask(
            chat=self.chat, sender=self.user, text="you retard"
        )
        self.assertTrue(out.changed)
        ev = ProfanityEvent.objects.get(user=self.user)
        self.assertEqual(ev.tier, ProfanityTier.T2_SLUR.value)
        self.assertEqual(LeakStrike.objects.get(user=self.user).count, 1)

    def test_disabled_flag_is_noop(self):
        out = self._svc(enabled=False).inspect_and_mask(
            chat=self.chat, sender=self.user, text="you motherfucker"
        )
        self.assertFalse(out.changed)
        self.assertEqual(out.text, "you motherfucker")
        self.assertFalse(ProfanityEvent.objects.filter(user=self.user).exists())
