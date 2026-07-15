"""Smoke tests for the shared factories (pytest-style + django_db)."""

from __future__ import annotations

import pytest

from apps.users.enums import VerificationStatus
from tests.factories import (
    OnboardedUserFactory,
    UserFactory,
    VerifiedUserFactory,
)

pytestmark = pytest.mark.django_db


def test_user_factory_creates_unique_users():
    a = UserFactory()
    b = UserFactory()
    assert a.id != b.id
    assert a.firebase_uid != b.firebase_uid


def test_onboarded_user_factory():
    user = OnboardedUserFactory()
    assert user.onboarding_completed_at is not None
    assert user.gender and user.intent


def test_verified_user_factory():
    user = VerifiedUserFactory()
    assert user.verification_status == VerificationStatus.APPROVED
    assert user.onboarding_completed_at is not None
