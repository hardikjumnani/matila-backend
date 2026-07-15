"""Tests for ReportService (audit/notifications mocked; real ChatService)."""

from __future__ import annotations

import uuid
from unittest import mock

from django.test import TestCase

from apps.chats.enums import ChatStatus, EndReason
from apps.chats.services.chat_service import ChatService
from apps.messaging.enums import MessageType
from apps.messaging.models import Message
from apps.reports.enums import ReportCategory, ReportStatus, ResolutionAction
from apps.reports.services.report_service import ReportService
from apps.users.enums import AccountStatus
from apps.users.models import User


def _user() -> User:
    return User.objects.create(
        firebase_uid="fb_" + uuid.uuid4().hex,
        college_email=f"{uuid.uuid4().hex}@college.edu",
    )


class ReportServiceTests(TestCase):
    def setUp(self) -> None:
        self.chats = ChatService(notification_service=mock.MagicMock())
        self.audit = mock.MagicMock()
        self.notifications = mock.MagicMock()
        self.service = ReportService(
            chat_service=self.chats,
            audit_service=self.audit,
            notification_service=self.notifications,
        )
        self.a = _user()
        self.b = _user()
        self.chat = self.chats.create_chat(self.a, self.b).data

    def test_submit_freezes_chat_and_sets_reported_user(self) -> None:
        result = self.service.submit_report(
            reporter=self.a, chat_id=str(self.chat.id), category=ReportCategory.SPAM
        )
        self.assertTrue(result.success)
        self.assertEqual(result.data.reported_user_id, self.b.id)
        self.chat.refresh_from_db()
        self.assertEqual(self.chat.status, ChatStatus.ENDED)
        self.assertEqual(self.chat.end_reason, EndReason.REPORT)
        self.audit.log.assert_called_once()

    def test_duplicate_report_conflict(self) -> None:
        self.service.submit_report(
            reporter=self.a, chat_id=str(self.chat.id), category=ReportCategory.SPAM
        )
        again = self.service.submit_report(
            reporter=self.a, chat_id=str(self.chat.id), category=ReportCategory.ABUSE
        )
        self.assertEqual(again.error_code, "CONFLICT")

    def test_non_participant_forbidden(self) -> None:
        result = self.service.submit_report(
            reporter=_user(), chat_id=str(self.chat.id), category=ReportCategory.SPAM
        )
        self.assertEqual(result.error_code, "FORBIDDEN")

    def test_invalid_reported_message(self) -> None:
        result = self.service.submit_report(
            reporter=self.a,
            chat_id=str(self.chat.id),
            category=ReportCategory.HARASSMENT,
            reported_message_id=str(uuid.uuid4()),
        )
        self.assertEqual(result.error_code, "VALIDATION_ERROR")

    def test_valid_reported_message(self) -> None:
        message = Message.objects.create(
            chat=self.chat,
            sender=self.b,
            message_type=MessageType.TEXT,
            text_content="x",
        )
        result = self.service.submit_report(
            reporter=self.a,
            chat_id=str(self.chat.id),
            category=ReportCategory.HARASSMENT,
            reported_message_id=str(message.id),
        )
        self.assertTrue(result.success)
        self.assertEqual(result.data.reported_message_id, message.id)

    def test_resolve_with_permanent_ban(self) -> None:
        report = self.service.submit_report(
            reporter=self.a, chat_id=str(self.chat.id), category=ReportCategory.ABUSE
        ).data
        result = self.service.resolve(
            report_id=str(report.id),
            admin_id="1",
            resolution_action=ResolutionAction.PERMANENT_BAN,
        )
        self.assertEqual(result.data.status, ReportStatus.RESOLVED)
        self.b.refresh_from_db()
        self.assertEqual(self.b.account_status, AccountStatus.BANNED)
        self.notifications.create_notification.assert_called_once()

    def test_resolve_temp_suspension(self) -> None:
        report = self.service.submit_report(
            reporter=self.a, chat_id=str(self.chat.id), category=ReportCategory.ABUSE
        ).data
        self.service.resolve(
            report_id=str(report.id),
            admin_id="1",
            resolution_action=ResolutionAction.TEMP_SUSPENSION,
        )
        self.b.refresh_from_db()
        self.assertEqual(self.b.account_status, AccountStatus.SUSPENDED)

    def test_dismiss_marks_false_report(self) -> None:
        report = self.service.submit_report(
            reporter=self.a, chat_id=str(self.chat.id), category=ReportCategory.OTHER
        ).data
        result = self.service.dismiss(
            report_id=str(report.id), admin_id="1", is_false_report=True
        )
        self.assertEqual(result.data.status, ReportStatus.DISMISSED)
        self.assertTrue(result.data.is_false_report)
        self.b.refresh_from_db()
        self.assertEqual(self.b.account_status, AccountStatus.ACTIVE)
