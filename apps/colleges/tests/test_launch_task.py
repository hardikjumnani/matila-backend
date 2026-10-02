"""Tests for the scheduled launch-notification task."""

from __future__ import annotations

import uuid
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.colleges.enums import LaunchMilestone
from apps.colleges.models import College, LaunchNotification
from apps.colleges.tasks.launch import send_launch_notifications
from apps.notifications.models import Notification
from apps.users.enums import AccountStatus, VerificationStatus
from apps.users.models import User


def _college(launch_offset: timedelta) -> College:
    return College.objects.create(
        code="C_" + uuid.uuid4().hex[:6],
        name="College",
        allowed_email_domains=["c.edu"],
        launch_date=timezone.now() + launch_offset,
    )


def _member(college: College, *, status=VerificationStatus.APPROVED,
            account=AccountStatus.ACTIVE) -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=f"{uuid.uuid4().hex}@c.edu",
        college=college,
        verification_status=status,
        account_status=account,
    )


class SendLaunchNotificationsTests(TestCase):
    def test_launch_fires_to_verified_members_only(self) -> None:
        college = _college(timedelta(minutes=-1))  # just launched
        approved = _member(college)
        _member(college, status=VerificationStatus.PENDING)  # excluded
        _member(college, account=AccountStatus.SUSPENDED)  # excluded
        other = _member(_college(timedelta(minutes=-1)))  # different college

        fired = send_launch_notifications()

        # LAUNCH is fresh; the three countdown milestones are long past -> suppressed.
        self.assertGreaterEqual(fired, 1)
        launch_notifs = Notification.objects.filter(
            type="college.launch.launch", user=approved
        )
        self.assertEqual(launch_notifs.count(), 1)
        # Non-eligible members of this college got nothing.
        self.assertEqual(
            Notification.objects.filter(
                user__college=college, type="college.launch.launch"
            ).count(),
            1,
        )
        # The other college's LAUNCH is its own row; this member got its own push.
        self.assertEqual(
            Notification.objects.filter(
                user=other, type="college.launch.launch"
            ).count(),
            1,
        )

    def test_is_idempotent(self) -> None:
        college = _college(timedelta(minutes=-1))
        member = _member(college)
        send_launch_notifications()
        fired_again = send_launch_notifications()
        self.assertEqual(fired_again, 0)
        self.assertEqual(
            Notification.objects.filter(
                user=member, type="college.launch.launch"
            ).count(),
            1,
        )

    def test_stale_milestone_recorded_but_not_sent(self) -> None:
        # Launch is 3 days out: T-7d is already in the past (>1h) -> suppressed.
        college = _college(timedelta(days=3))
        member = _member(college)

        fired = send_launch_notifications()

        self.assertEqual(fired, 0)
        self.assertTrue(
            LaunchNotification.objects.filter(
                college=college, milestone=LaunchMilestone.T_MINUS_7D
            ).exists()
        )
        self.assertFalse(Notification.objects.filter(user=member).exists())

    def test_fresh_countdown_milestone_fires(self) -> None:
        # Launch ~1 day away: the T-1d trigger just passed (fresh) -> sends.
        college = _college(timedelta(days=1) - timedelta(minutes=1))
        member = _member(college)

        send_launch_notifications()

        self.assertEqual(
            Notification.objects.filter(
                user=member, type="college.launch.t_minus_1d"
            ).count(),
            1,
        )

    def test_future_launch_sends_nothing(self) -> None:
        college = _college(timedelta(days=30))
        _member(college)
        fired = send_launch_notifications()
        self.assertEqual(fired, 0)
        self.assertFalse(Notification.objects.filter(user__college=college).exists())

    def test_inactive_college_skipped(self) -> None:
        college = _college(timedelta(minutes=-1))
        college.is_active = False
        college.save(update_fields=["is_active"])
        _member(college)
        fired = send_launch_notifications()
        self.assertEqual(fired, 0)
