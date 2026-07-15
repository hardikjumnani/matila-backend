"""Scheduled task: time out stale matchmaking queue entries."""

from __future__ import annotations

import logging

from celery import shared_task

from apps.configuration.services.configuration_service import ConfigurationService
from apps.matchmaking.services.matchmaking_service import MatchmakingService

logger = logging.getLogger(__name__)


@shared_task(name="apps.matchmaking.tasks.cleanup_stale_match_queue")
def cleanup_stale_match_queue() -> int:
    """Mark searching entries whose heartbeat lapsed as TIMEOUT."""
    timeout = ConfigurationService().get_matchmaking_timeout_seconds()
    removed = MatchmakingService().cleanup_stale(timeout_seconds=timeout)
    if removed:
        logger.info("cleanup_stale_match_queue timed out %d entrie(s).", removed)
    return removed
