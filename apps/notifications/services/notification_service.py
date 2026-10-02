"""
Notification service.

Owns ``notifications``. Implements the in-app notification lifecycle: creating
records, computing unread counts, and marking notifications read.

Push (FCM) delivery is intentionally NOT wired here yet. It is completed in
Step 8 alongside the delivery task, and depends on a resolution to the device-
token storage gap (the frozen schema has no place to store FCM registration
tokens). New notifications are created with ``push_status = PENDING`` so the
Step 8 delivery pipeline can pick them up once that gap is resolved.
"""

from __future__ import annotations

import atexit
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any

from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.common.results import ServiceResult
from apps.notifications.enums import NotificationPriority
from apps.notifications.models import Notification
from apps.users.models import User

logger = logging.getLogger(__name__)

# Celery's first task-publish on any thread pays a one-time cold cost (app
# finalize + per-thread broker connection) of several seconds. On an ASGI server
# that runs sync views in a thread pool, paying this on the request thread makes
# the first action on each worker thread hang. Route every enqueue through one
# long-lived publisher thread instead: it warms once, stays hot, and request
# threads hand off and return immediately. Push is best-effort, so a dropped
# enqueue is recoverable from the notification's PENDING push_status.
_push_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="push-enqueue")
atexit.register(_push_executor.shutdown, wait=False)


class NotificationService:
    """Create and manage in-app notifications."""

    def create_notification(
        self,
        *,
        user: User,
        type: str,
        title: str,
        body: str = "",
        action_type: str = "",
        action_payload: dict[str, Any] | None = None,
        priority: NotificationPriority | str = NotificationPriority.NORMAL,
        metadata: dict[str, Any] | None = None,
        expires_at: datetime | None = None,
        push: bool = True,
    ) -> Notification:
        """Create an in-app notification and (optionally) enqueue FCM delivery.

        Delivery is enqueued only after the surrounding transaction commits, so
        the worker never races ahead of a row that might roll back.
        """
        notification = Notification.objects.create(
            user=user,
            type=type,
            title=title,
            body=body,
            action_type=action_type,
            action_payload=action_payload or {},
            priority=priority,
            metadata=metadata or {},
            expires_at=expires_at,
        )
        logger.info(
            "Notification %s created for user %s (type=%s)",
            notification.id,
            user.id,
            type,
        )
        if push:
            self._enqueue_push(str(notification.id))
        return notification

    def _enqueue_push(self, notification_id: str) -> None:
        """Enqueue FCM delivery after commit; best-effort (never blocks creation).

        The actual broker publish runs on the shared single-thread executor so the
        caller's thread (often an ASGI request thread) never waits on Celery's
        connection setup.
        """

        def _publish() -> None:
            try:
                from apps.notifications.tasks import send_push_notification

                send_push_notification.delay(notification_id)
            except Exception as exc:  # noqa: BLE001 — broker down must not break.
                # The PENDING push_status lets a future sweep retry delivery.
                logger.warning(
                    "Could not enqueue push for %s: %s", notification_id, exc
                )

        # After commit, hand the publish off to the warm publisher thread and
        # return at once (submit is non-blocking).
        transaction.on_commit(lambda: _push_executor.submit(_publish))

    def for_user(self, user: User) -> QuerySet[Notification]:
        """Return a user's non-expired notifications, newest first."""
        now = timezone.now()
        return Notification.objects.filter(user=user).filter(
            Q(expires_at__isnull=True) | Q(expires_at__gt=now)
        )

    def get_unread_count(self, user: User) -> int:
        """Return the count of unread, non-expired notifications for a user."""
        return self.for_user(user).filter(is_read=False).count()

    def mark_read(
        self, *, user: User, notification_id: str
    ) -> ServiceResult[Notification]:
        """Mark a single notification read. Idempotent for already-read rows."""
        notification = Notification.objects.filter(
            id=notification_id, user=user
        ).first()
        if notification is None:
            return ServiceResult.fail("RESOURCE_NOT_FOUND", "Notification not found.")
        if not notification.is_read:
            notification.is_read = True
            notification.read_at = timezone.now()
            notification.save(update_fields=["is_read", "read_at"])
        return ServiceResult.ok(notification)

    def mark_all_read(self, *, user: User) -> int:
        """Mark all of a user's unread notifications read; return the count."""
        return Notification.objects.filter(user=user, is_read=False).update(
            is_read=True, read_at=timezone.now()
        )
