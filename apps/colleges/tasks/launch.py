"""
Scheduled task: college launch-countdown notifications.

Sweeps active colleges with a scheduled ``launch_date`` and fires the countdown
milestones (T-7d, T-1d, T-1h, LAUNCH) to each college's verified members. Each
milestone is sent exactly once per college via a ``LaunchNotification`` row
(unique on ``(college, milestone)``), so re-runs and overlapping beats are safe.

A milestone is sent only when it became due *recently* (within ``_FRESH_WINDOW``):
a launch date set with little runway — or edited into the past — records the
already-passed milestones without blasting stale "7 days to go" pushes. The only
per-user message not handled here is the "you're verified" note, which is sent
inline on approval (see VerificationService).
"""

from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.db import IntegrityError
from django.utils import timezone

from apps.colleges.enums import LaunchMilestone
from apps.colleges.models import College, LaunchNotification
from apps.users.enums import AccountStatus, VerificationStatus
from apps.users.models import User

logger = logging.getLogger(__name__)

# How long before launch each milestone fires.
_OFFSETS: dict[str, timedelta] = {
    LaunchMilestone.T_MINUS_7D: timedelta(days=7),
    LaunchMilestone.T_MINUS_1D: timedelta(days=1),
    LaunchMilestone.T_MINUS_1H: timedelta(hours=1),
    LaunchMilestone.LAUNCH: timedelta(0),
}

# A milestone is only *sent* if it became due within this window; older ones are
# recorded-and-suppressed. Comfortably larger than the beat interval so a few
# missed runs still deliver.
_FRESH_WINDOW = timedelta(hours=1)


def _copy(milestone: str, college: College) -> tuple[str, str, str]:
    """(title, body, action_type) for a milestone push."""
    name = college.name
    if milestone == LaunchMilestone.T_MINUS_7D:
        return ("1 week to launch 🎉", f"Matila goes live at {name} in 7 days.", "")
    if milestone == LaunchMilestone.T_MINUS_1D:
        return ("Launching tomorrow 🚀", f"Matila opens at {name} tomorrow.", "")
    if milestone == LaunchMilestone.T_MINUS_1H:
        return ("1 hour to go ⏳", f"Matila opens at {name} in an hour.", "")
    return (
        "Matila is live! 🎊",
        f"Matching just opened at {name}. Jump in.",
        "OPEN_APP",
    )


def _send_milestone(college: College, milestone: str) -> int:
    """Push one milestone to every verified, active member of the college."""
    from apps.notifications.services.notification_service import NotificationService

    title, body, action_type = _copy(milestone, college)
    notifications = NotificationService()
    recipients = User.objects.filter(
        college=college,
        verification_status=VerificationStatus.APPROVED,
        account_status=AccountStatus.ACTIVE,
    )
    sent = 0
    for user in recipients.iterator():
        notifications.create_notification(
            user=user,
            type=f"college.launch.{milestone.lower()}",
            title=title,
            body=body,
            action_type=action_type,
        )
        sent += 1
    logger.info(
        "Launch milestone %s for college %s -> %d recipient(s).",
        milestone,
        college.code,
        sent,
    )
    return sent


@shared_task(name="apps.colleges.tasks.send_launch_notifications")
def send_launch_notifications() -> int:
    """Fire any newly-due launch milestones across active colleges (idempotent).

    Returns the number of milestones *sent* this run (suppressed stale ones do
    not count)."""
    now = timezone.now()
    fired = 0
    colleges = College.objects.filter(is_active=True, launch_date__isnull=False)
    for college in colleges:
        for milestone, offset in _OFFSETS.items():
            trigger = college.launch_date - offset
            if now < trigger:
                continue  # not due yet
            try:
                _, created = LaunchNotification.objects.get_or_create(
                    college=college, milestone=milestone
                )
            except IntegrityError:
                # Lost a race with a concurrent beat — already handled.
                continue
            if not created:
                continue  # already handled on a prior run
            if now - trigger > _FRESH_WINDOW:
                # Milestone passed long ago (launch set/edited late); record it
                # as handled but don't blast a stale push.
                logger.info(
                    "Suppressed stale milestone %s for college %s (%s late).",
                    milestone,
                    college.code,
                    now - trigger,
                )
                continue
            _send_milestone(college, milestone)
            fired += 1
    return fired
