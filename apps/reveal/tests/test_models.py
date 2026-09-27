"""Smoke tests for the decision-round models."""

from __future__ import annotations

import uuid

from django.db import IntegrityError
from django.test import TestCase

from apps.chats.services.chat_service import ChatService
from apps.reveal.enums import DecisionRoundPhase, RevealTrigger
from apps.reveal.models import DecisionRound, ParticipantDecision
from apps.users.models import User


def _user() -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=f"{uuid.uuid4().hex}@college.edu",
        gender="MALE",
        intent="RELATIONSHIP",
    )


class DecisionModelTests(TestCase):
    def setUp(self) -> None:
        self.a = _user()
        self.b = _user()
        self.chat = ChatService().create_chat(self.a, self.b).data

    def test_round_defaults(self) -> None:
        r = DecisionRound.objects.create(chat=self.chat, trigger=RevealTrigger.EXPIRY)
        self.assertEqual(r.phase, DecisionRoundPhase.DECISION)
        self.assertEqual(r.final_call, "")

    def test_participant_decision_unique_per_round_user(self) -> None:
        r = DecisionRound.objects.create(chat=self.chat, trigger=RevealTrigger.MID_CHAT)
        ParticipantDecision.objects.create(round=r, user=self.a)
        with self.assertRaises(IntegrityError):
            ParticipantDecision.objects.create(round=r, user=self.a)
