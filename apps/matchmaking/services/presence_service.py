"""
Global presence service.

Tracks "who is online in the app right now" in a Redis sorted set keyed by
last-seen epoch, fed by ``POST /presence/heartbeat`` (the app pings while
foregrounded). Powers the lobby stats (total/compatible online). Distinct from
the per-chat WebSocket presence and from the matchmaking queue.

Degrades gracefully: if Redis is unavailable/unconfigured (e.g. the test env),
heartbeats are no-ops and counts read as empty — the lobby simply shows "0+".
See docs/LOBBY_STATS_PLAN.md.
"""

from __future__ import annotations

import logging
import time

from django.conf import settings

from apps.matchmaking.constants import PRESENCE_ONLINE_WINDOW_SECONDS

logger = logging.getLogger(__name__)

_ONLINE_KEY = "presence:online"


class PresenceService:
    def __init__(self) -> None:
        self._client = None
        self._resolved = False

    @property
    def _redis(self):
        """Lazily resolve a raw Redis client (None when unconfigured)."""
        if not self._resolved:
            self._resolved = True
            url = getattr(settings, "REDIS_URL", "") or ""
            if url:
                try:
                    import redis

                    self._client = redis.from_url(url)
                except Exception as exc:  # noqa: BLE001 — presence is best-effort.
                    logger.warning("Presence Redis unavailable: %s", exc)
                    self._client = None
        return self._client

    def heartbeat(self, user_id) -> None:
        """Mark a user online now and opportunistically prune stale entries."""
        client = self._redis
        if client is None:
            return
        now = time.time()
        try:
            client.zadd(_ONLINE_KEY, {str(user_id): now})
            client.zremrangebyscore(_ONLINE_KEY, 0, now - PRESENCE_ONLINE_WINDOW_SECONDS)
        except Exception as exc:  # noqa: BLE001 — never fail a request on presence.
            logger.warning("Presence heartbeat failed: %s", exc)

    def online_count(self) -> int:
        client = self._redis
        if client is None:
            return 0
        now = time.time()
        try:
            return int(
                client.zcount(_ONLINE_KEY, now - PRESENCE_ONLINE_WINDOW_SECONDS, "+inf")
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Presence count failed: %s", exc)
            return 0

    def online_ids(self) -> set[str]:
        """The set of user-ids seen within the online window."""
        client = self._redis
        if client is None:
            return set()
        now = time.time()
        try:
            members = client.zrangebyscore(
                _ONLINE_KEY, now - PRESENCE_ONLINE_WINDOW_SECONDS, "+inf"
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Presence ids failed: %s", exc)
            return set()
        return {m.decode() if isinstance(m, bytes) else str(m) for m in members}
