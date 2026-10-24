"""Tests for the per-user match block list (BlockedName)."""

from __future__ import annotations

import uuid

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.users.models import BlockedName, User
from apps.users.name_match import name_is_blocked, name_tokens, normalize_name
from apps.users.services.block_list_service import BlockListService


def _user() -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=f"{uuid.uuid4().hex}@college.edu",
        onboarding_completed_at=timezone.now(),  # launched (UNASSIGNED) -> edits allowed
    )


class NameMatchTests(TestCase):
    def test_normalize_and_tokens(self):
        self.assertEqual(normalize_name("  Café  JOSÉ "), "cafe jose")
        self.assertEqual(name_tokens("Himanshu-Chauhan"), {"himanshu", "chauhan"})

    def test_first_name_blocks_any_match(self):
        self.assertTrue(name_is_blocked(["himanshu"], "Himanshu Chauhan"))
        self.assertTrue(name_is_blocked(["chauhan"], "Himanshu Chauhan"))

    def test_full_name_blocks_only_that_pair(self):
        self.assertTrue(name_is_blocked(["himanshu chauhan"], "Himanshu Chauhan"))
        self.assertFalse(name_is_blocked(["himanshu chauhan"], "Himanshu Kumar"))

    def test_case_and_accent_insensitive(self):
        self.assertTrue(name_is_blocked([normalize_name("José")], "jose garcia"))

    def test_token_equality_not_substring(self):
        self.assertFalse(name_is_blocked(["himanshu"], "himanshuda rocks"))

    def test_empty_target_or_list(self):
        self.assertFalse(name_is_blocked(["himanshu"], ""))
        self.assertFalse(name_is_blocked([], "Himanshu"))


class BlockListServiceTests(TestCase):
    def setUp(self) -> None:
        self.user = _user()
        self.svc = BlockListService()

    def test_set_trims_dedupes_drops_blanks(self):
        self.svc.set_names(self.user, [" Himanshu ", "himanshu", "", "  ", "José", "Jose"])
        names = set(
            BlockedName.objects.filter(user=self.user).values_list("name_normalized", flat=True)
        )
        self.assertEqual(names, {"himanshu", "jose"})  # case + accent dedupe

    def test_replace_is_full(self):
        self.svc.set_names(self.user, ["A", "B"])
        self.svc.set_names(self.user, ["C"])
        self.assertEqual(
            list(BlockedName.objects.filter(user=self.user).values_list("name", flat=True)),
            ["C"],
        )

    def test_caps_count_and_length(self):
        self.svc.set_names(self.user, [f"name{i}" for i in range(150)])
        self.assertEqual(BlockedName.objects.filter(user=self.user).count(), 100)
        self.svc.set_names(self.user, ["x" * 80])
        row = BlockedName.objects.filter(user=self.user).first()
        self.assertLessEqual(len(row.name), 50)


class BlockListApiTests(TestCase):
    def setUp(self) -> None:
        self.user = _user()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_patch_sets_and_get_returns(self):
        resp = self.client.patch(
            "/api/v1/users/me",
            {"match_block_names": ["Himanshu", "Rahul"]},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(BlockedName.objects.filter(user=self.user).count(), 2)
        got = self.client.get("/api/v1/users/me").json()["data"]["match_block_names"]
        self.assertEqual(set(got), {"Himanshu", "Rahul"})

    def test_patch_empty_clears(self):
        BlockListService().set_names(self.user, ["Himanshu"])
        resp = self.client.patch(
            "/api/v1/users/me", {"match_block_names": []}, format="json"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(BlockedName.objects.filter(user=self.user).count(), 0)

    def test_over_cap_count_rejected(self):
        resp = self.client.patch(
            "/api/v1/users/me",
            {"match_block_names": [f"n{i}" for i in range(101)]},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_over_cap_length_rejected(self):
        resp = self.client.patch(
            "/api/v1/users/me",
            {"match_block_names": ["x" * 51]},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
