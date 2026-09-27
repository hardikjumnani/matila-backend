"""
Shared factory-boy factories for tests.

Lives outside the installed apps so application/production code never imports
``factory`` (a development-only dependency). Import in tests as
``from tests.factories import UserFactory``.
"""

from __future__ import annotations

import uuid

import factory
from factory.django import DjangoModelFactory

from apps.chats.models import Chat
from apps.users.enums import Gender, Intent, VerificationStatus
from apps.users.models import User


class UserFactory(DjangoModelFactory):
    class Meta:
        model = User

    firebase_uid = factory.LazyFunction(lambda: "fb_" + uuid.uuid4().hex)
    college_email = factory.LazyFunction(lambda: f"{uuid.uuid4().hex}@college.edu")
    full_name = factory.Sequence(lambda n: f"Test User {n}")


class OnboardedUserFactory(UserFactory):
    """A user who has completed onboarding (profile fields set)."""

    gender = Gender.MALE
    intent = Intent.RELATIONSHIP
    gender_preferences = factory.LazyFunction(lambda: [Gender.FEMALE])
    onboarding_completed_at = factory.Faker("date_time_this_year", tzinfo=None)


class VerifiedUserFactory(OnboardedUserFactory):
    """An onboarded, verification-approved user (eligible for matchmaking)."""

    verification_status = VerificationStatus.APPROVED


class ChatFactory(DjangoModelFactory):
    class Meta:
        model = Chat
