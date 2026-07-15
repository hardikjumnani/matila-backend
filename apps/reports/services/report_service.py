"""
Report service.

Owns ``reports`` and drives moderation. Submitting a report immediately freezes
the chat (ends it with reason=REPORT), preserving all history for review. A user
may file at most one report per chat. Admin moderation resolves or dismisses a
report and may change the reported user's account status.
"""

from __future__ import annotations

import logging

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.enums import ActorType
from apps.chats.enums import EndReason
from apps.chats.models import ChatParticipant
from apps.common.results import ServiceResult
from apps.reports.enums import ReportStatus, ResolutionAction
from apps.reports.models import Report
from apps.users.enums import AccountStatus
from apps.users.models import User

logger = logging.getLogger(__name__)

# Resolution actions that change the reported user's account status.
_ACCOUNT_ACTIONS = {
    ResolutionAction.TEMP_SUSPENSION: AccountStatus.SUSPENDED,
    ResolutionAction.PERMANENT_BAN: AccountStatus.BANNED,
}


class ReportService:
    """Report submission and moderation."""

    def __init__(
        self, *, chat_service=None, audit_service=None, notification_service=None
    ) -> None:
        if chat_service is None:
            from apps.chats.services.chat_service import ChatService

            chat_service = ChatService()
        if audit_service is None:
            from apps.audit.services.audit_service import AuditService

            audit_service = AuditService()
        if notification_service is None:
            from apps.notifications.services.notification_service import (
                NotificationService,
            )

            notification_service = NotificationService()
        self._chats = chat_service
        self._audit = audit_service
        self._notifications = notification_service

    # -- Submission ---------------------------------------------------------

    def submit_report(
        self,
        *,
        reporter: User,
        chat_id: str,
        category: str,
        description: str = "",
        reported_message_id: str | None = None,
    ) -> ServiceResult[Report]:
        """File a report and immediately freeze the chat."""
        chat = self._chats.get_chat(chat_id)
        if chat is None:
            return ServiceResult.fail("RESOURCE_NOT_FOUND", "Chat not found.")
        if not self._chats.is_participant(chat, reporter):
            return ServiceResult.fail("FORBIDDEN", "You are not in this chat.")

        other = (
            ChatParticipant.objects.select_related("user")
            .filter(chat=chat)
            .exclude(user=reporter)
            .first()
        )
        if other is None:
            return ServiceResult.fail(
                "VALIDATION_ERROR", "Chat has no other participant to report."
            )
        reported_user = other.user

        reported_message = None
        if reported_message_id:
            from apps.messaging.models import Message

            reported_message = Message.objects.filter(
                id=reported_message_id, chat=chat
            ).first()
            if reported_message is None:
                return ServiceResult.fail(
                    "VALIDATION_ERROR", "Reported message is not in this chat."
                )

        try:
            with transaction.atomic():
                report = Report.objects.create(
                    chat=chat,
                    reported_by=reporter,
                    reported_user=reported_user,
                    category=category,
                    description=description,
                    reported_message=reported_message,
                    status=ReportStatus.OPEN,
                )
        except IntegrityError:
            # Backs the one-report-per-chat-per-user unique constraint against a
            # concurrent double submission.
            return ServiceResult.fail(
                "CONFLICT", "You have already reported this chat."
            )

        # Freezing the chat is idempotent, so re-reporting an already-ended chat
        # is safe.
        self._chats.end_chat(chat_id, reason=EndReason.REPORT)
        self._audit.log(
            actor_type=ActorType.USER,
            actor_id=str(reporter.id),
            action="report.submitted",
            entity_type="report",
            entity_id=str(report.id),
            metadata={"chat_id": str(chat.id), "category": category},
        )
        logger.info("Report %s filed on chat %s", report.id, chat.id)
        return ServiceResult.ok(report)

    # -- Reads --------------------------------------------------------------

    def get_reports_by(self, user: User):
        return Report.objects.filter(reported_by=user).order_by("-created_at")

    def get_report_for_reporter(self, *, report_id: str, user: User) -> Report | None:
        return Report.objects.filter(id=report_id, reported_by=user).first()

    # -- Moderation ---------------------------------------------------------

    def resolve(
        self,
        *,
        report_id: str,
        admin_id: str,
        resolution_action: ResolutionAction | str,
        admin_notes: str = "",
        is_false_report: bool = False,
    ) -> ServiceResult[Report]:
        """Resolve a report and apply any account action to the reported user."""
        with transaction.atomic():
            report = (
                Report.objects.select_for_update()
                .select_related("reported_user")
                .filter(id=report_id)
                .first()
            )
            if report is None:
                return ServiceResult.fail("RESOURCE_NOT_FOUND", "Report not found.")

            now = timezone.now()
            report.status = ReportStatus.RESOLVED
            report.resolution_action = resolution_action
            report.admin_notes = admin_notes
            report.is_false_report = is_false_report
            report.reviewed_at = now
            report.status_changed_at = now
            report.save(
                update_fields=[
                    "status",
                    "resolution_action",
                    "admin_notes",
                    "is_false_report",
                    "reviewed_at",
                    "status_changed_at",
                ]
            )

            new_account_status = _ACCOUNT_ACTIONS.get(resolution_action)
            reported_user = report.reported_user
            if new_account_status is not None:
                reported_user.account_status = new_account_status
                reported_user.save(update_fields=["account_status", "updated_at"])

        self._audit.log(
            actor_type=ActorType.ADMIN,
            actor_id=admin_id,
            action="report.resolved",
            entity_type="report",
            entity_id=str(report.id),
            metadata={
                "resolution_action": str(resolution_action),
                "reported_user_id": str(reported_user.id),
            },
        )
        if new_account_status is not None:
            self._notify_account_action(reported_user, new_account_status)
        logger.info("Report %s resolved (%s)", report.id, resolution_action)
        return ServiceResult.ok(report)

    def dismiss(
        self,
        *,
        report_id: str,
        admin_id: str,
        is_false_report: bool = False,
        admin_notes: str = "",
    ) -> ServiceResult[Report]:
        """Dismiss a report without action, optionally flagging it as false."""
        with transaction.atomic():
            report = Report.objects.select_for_update().filter(id=report_id).first()
            if report is None:
                return ServiceResult.fail("RESOURCE_NOT_FOUND", "Report not found.")
            now = timezone.now()
            report.status = ReportStatus.DISMISSED
            report.resolution_action = ResolutionAction.NO_ACTION
            report.is_false_report = is_false_report
            report.admin_notes = admin_notes
            report.reviewed_at = now
            report.status_changed_at = now
            report.save(
                update_fields=[
                    "status",
                    "resolution_action",
                    "is_false_report",
                    "admin_notes",
                    "reviewed_at",
                    "status_changed_at",
                ]
            )

        self._audit.log(
            actor_type=ActorType.ADMIN,
            actor_id=admin_id,
            action="report.dismissed",
            entity_type="report",
            entity_id=str(report.id),
            metadata={"is_false_report": is_false_report},
        )
        return ServiceResult.ok(report)

    # -- Internal -----------------------------------------------------------

    def _notify_account_action(self, user: User, status: str) -> None:
        self._notifications.create_notification(
            user=user,
            type="account.status_changed",
            title="Account status update",
            body=f"Your account status has changed to {status}.",
            priority="HIGH",
        )
