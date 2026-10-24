"""Matchmaking integration for the per-user name block list (mutual)."""

from __future__ import annotations

import uuid

from django.test import TestCase
from django.utils import timezone

from apps.matchmaking.services.matchmaking_service import MatchmakingService
from apps.users.enums import Gender, Intent, VerificationStatus
from apps.users.models import User
from apps.users.services.block_list_service import BlockListService


def _eligible(full_name="") -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=f"{uuid.uuid4().hex}@college.edu",
        full_name=full_name,
        gender=Gender.OTHER,
        intent=Intent.RELATIONSHIP,
        gender_preferences=[],  # no restriction -> always gender-compatible
        verification_status=VerificationStatus.APPROVED,
        onboarding_completed_at=timezone.now(),
    )


class BlockNameMatchTests(TestCase):
    def setUp(self) -> None:
        self.svc = MatchmakingService()

    def test_blocked_name_prevents_match(self):
        a = _eligible()
        b = _eligible(full_name="Himanshu Chauhan")
        BlockListService().set_names(a, ["Himanshu"])
        self.svc.join(b)  # b is searching
        res = self.svc.join(a)
        self.assertTrue(res.success)
        self.assertFalse(res.data.matched)  # a did not match the blocked Himanshu

    def test_reverse_block_prevents_match(self):
        a = _eligible(full_name="Rahul Verma")
        b = _eligible(full_name="Some One")
        BlockListService().set_names(b, ["rahul"])  # b blocks a's name
        self.svc.join(b)
        res = self.svc.join(a)
        self.assertFalse(res.data.matched)  # mutual: b's block stops the pair

    def test_unblocked_pair_matches(self):
        a = _eligible(full_name="Alice Able")
        b = _eligible(full_name="Himanshu Chauhan")
        self.svc.join(b)
        res = self.svc.join(a)
        self.assertTrue(res.data.matched)

    def test_full_name_block_is_specific(self):
        a = _eligible()
        b = _eligible(full_name="Himanshu Kumar")  # different surname
        BlockListService().set_names(a, ["Himanshu Chauhan"])  # full name, not this one
        self.svc.join(b)
        res = self.svc.join(a)
        self.assertTrue(res.data.matched)  # not the blocked full name -> matches
