"""
Push-notification delivery task.

Delivers a persisted notification to the user's active devices via FCM, records
the resulting push status, and deactivates any tokens FCM reports as dead. Idem-
potent (a notification already SENT is skipped) and retried on transient errors.
"""

from __future__ import annotations

import json
import logging

from celery import shared_task

from apps.common import firebase
from apps.notifications.enums import PushStatus
from apps.notifications.models import Notification
from apps.notifications.services.device_token_service import DeviceTokenService

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    acks_late=True,
)
def send_push_notification(self, notification_id: str) -> None:
    """Send FCM push for a single notification."""
    notification = (
        Notification.objects.select_related("user").filter(id=notification_id).first()
    )
    if notification is None:
        return
    if notification.push_status == PushStatus.SENT:
        return  # Idempotent: already delivered.

    device_service = DeviceTokenService()
    tokens = list(
        device_service.active_tokens_for(notification.user).values_list(
            "token", flat=True
        )
    )
    if not tokens:
        _set_status(notification, PushStatus.SKIPPED)
        return

    data = {
        "type": notification.type,
        "action_type": notification.action_type,
        "action_payload": json.dumps(notification.action_payload or {}),
    }
    try:
        result = firebase.send_push(
            tokens, title=notification.title, body=notification.body, data=data
        )
    except firebase.FirebaseNotConfigured:
        # No credentials in this environment — treat as skipped, do not retry.
        _set_status(notification, PushStatus.SKIPPED)
        return
    except Exception as exc:  # noqa: BLE001 — transient FCM/network failure.
        _set_status(notification, PushStatus.FAILED)
        logger.warning("Push delivery failed for %s: %s", notification_id, exc)
        raise self.retry(exc=exc)

    if result.invalid_tokens:
        device_service.deactivate_tokens(result.invalid_tokens)

    _set_status(
        notification,
        PushStatus.SENT if result.success_count else PushStatus.FAILED,
    )


def _set_status(notification: Notification, status: str) -> None:
    notification.push_status = status
    notification.save(update_fields=["push_status"])
