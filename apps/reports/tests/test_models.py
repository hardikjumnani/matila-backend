"""Model tests for the reports domain."""

from __future__ import annotations

import uuid

from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.chats.models import Chat
from apps.reports.enums import ReportCategory, ReportStatus, ResolutionAction
from apps.reports.models import Report
from apps.users.models import User


def _user() -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=f"{uuid.uuid4().hex}@college.edu",
    )


class ReportModelTests(TestCase):
    def test_defaults(self) -> None:
        report = Report.objects.create(
            chat=Chat.objects.create(),
            reported_by=_user(),
            reported_user=_user(),
            category=ReportCategory.HARASSMENT,
        )
        self.assertEqual(report.status, ReportStatus.OPEN)
        self.assertEqual(report.resolution_action, ResolutionAction.NONE)
        self.assertFalse(report.is_false_report)

    def test_one_report_per_chat_per_reporter(self) -> None:
        chat = Chat.objects.create()
        reporter = _user()
        target = _user()
        Report.objects.create(
            chat=chat,
            reported_by=reporter,
            reported_user=target,
            category=ReportCategory.SPAM,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            Report.objects.create(
                chat=chat,
                reported_by=reporter,
                reported_user=target,
                category=ReportCategory.ABUSE,
            )
