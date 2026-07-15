"""Model tests for the users domain."""

from __future__ import annotations

import uuid

from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.users.enums import AccountStatus, VerificationStatus
from apps.users.models import User


class UserModelTests(TestCase):
    def _create(self, **overrides) -> User:
        data = {
            "firebase_uid": "fb_" + uuid.uuid4().hex,
            "college_email": f"{uuid.uuid4().hex}@college.edu",
        }
        data.update(overrides)
        return User.objects.create(**data)

    def test_primary_key_is_uuid(self) -> None:
        user = self._create()
        self.assertIsInstance(user.id, uuid.UUID)

    def test_default_statuses(self) -> None:
        user = self._create()
        self.assertEqual(user.verification_status, VerificationStatus.PENDING)
        self.assertEqual(user.account_status, AccountStatus.ACTIVE)
        self.assertEqual(user.gender_preferences, [])

    def test_firebase_uid_is_unique(self) -> None:
        self._create(firebase_uid="duplicate")
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._create(firebase_uid="duplicate")

    def test_college_email_is_unique(self) -> None:
        self._create(college_email="dup@college.edu")
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._create(college_email="dup@college.edu")
