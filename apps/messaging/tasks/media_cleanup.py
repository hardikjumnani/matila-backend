"""Scheduled task: delete expired/consumed chat media from storage."""

from __future__ import annotations

import logging

from celery import shared_task
from django.db.models import Q
from django.utils import timezone

from apps.common.services.storage_service import StorageService
from apps.messaging.enums import MediaStatus, MessageType
from apps.messaging.models import Message

logger = logging.getLogger(__name__)


@shared_task(name="apps.messaging.tasks.cleanup_expired_media")
def cleanup_expired_media() -> int:
    """Delete S3 objects for consumed view-once media and images past 7 days.

    Deletes the storage object and marks ``media_status = DELETED`` while keeping
    the message row for chat history. Idempotent and safe against already-deleted
    S3 objects (StorageService.delete_object swallows missing keys).
    """
    now = timezone.now()
    storage = StorageService()
    queryset = Message.objects.filter(message_type=MessageType.IMAGE).filter(
        Q(media_status=MediaStatus.VIEWED)
        | Q(media_status=MediaStatus.AVAILABLE, media_expires_at__lte=now)
    )

    deleted = 0
    for message in queryset.iterator():
        if message.media_url:
            storage.delete_object(message.media_url)
        message.media_status = MediaStatus.DELETED
        message.save(update_fields=["media_status"])
        deleted += 1
    if deleted:
        logger.info("cleanup_expired_media deleted %d media object(s).", deleted)
    return deleted
