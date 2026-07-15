"""
Dashboard statistics service.

Read-only operational aggregates for the admin dashboard. Uses efficient
COUNT/SUM aggregates rather than loading rows.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Sum

from apps.chats.enums import ChatStatus
from apps.chats.models import Chat
from apps.payments.enums import PaymentPurpose, PaymentStatus
from apps.payments.models import Payment
from apps.reports.enums import ReportStatus
from apps.reports.models import Report
from apps.users.enums import AccountStatus, VerificationStatus
from apps.users.models import User


class DashboardService:
    """Operational statistics for the admin dashboard."""

    def get_stats(self) -> dict[str, Any]:
        return {
            "users": self._user_stats(),
            "verifications": self._verification_stats(),
            "chats": self._chat_stats(),
            "reports": self._report_stats(),
            "revenue": self._revenue_stats(),
        }

    def _user_stats(self) -> dict[str, int]:
        return {
            "total": User.objects.count(),
            "verified": User.objects.filter(
                verification_status=VerificationStatus.APPROVED
            ).count(),
            "active": User.objects.filter(account_status=AccountStatus.ACTIVE).count(),
            "suspended": User.objects.filter(
                account_status=AccountStatus.SUSPENDED
            ).count(),
            "banned": User.objects.filter(account_status=AccountStatus.BANNED).count(),
        }

    def _verification_stats(self) -> dict[str, int]:
        return {
            "pending": User.objects.filter(
                verification_status=VerificationStatus.PENDING
            ).count(),
        }

    def _chat_stats(self) -> dict[str, int]:
        return {
            "total": Chat.objects.count(),
            "active": Chat.objects.filter(
                status__in=[ChatStatus.ACTIVE, ChatStatus.EXTENDED]
            ).count(),
            "revealed": Chat.objects.filter(status=ChatStatus.REVEALED).count(),
        }

    def _report_stats(self) -> dict[str, int]:
        return {
            "open": Report.objects.filter(status=ReportStatus.OPEN).count(),
        }

    def _revenue_stats(self) -> dict[str, int]:
        successful = Payment.objects.filter(status=PaymentStatus.SUCCESS)

        def _sum(purpose: str | None = None) -> int:
            queryset = (
                successful if purpose is None else successful.filter(purpose=purpose)
            )
            return queryset.aggregate(total=Sum("amount_in_paise"))["total"] or 0

        return {
            "total_paise": _sum(),
            "reveal_paise": _sum(PaymentPurpose.REVEAL),
            "extension_paise": _sum(PaymentPurpose.CHAT_EXTENSION),
        }
