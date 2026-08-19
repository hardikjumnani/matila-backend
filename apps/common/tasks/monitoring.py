"""
Scheduled monitoring: sample core runtime health metrics and surface breaches.

Free by design (no Log Analytics ingestion): the values are logged every run so
they are visible via ``journalctl``, and a threshold breach is captured as a
Sentry ``warning`` event (which alerts by email). Covers the plan's core
metrics: Redis memory, Celery backlog, and database connections.
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.conf import settings
from django.db import connection

logger = logging.getLogger(__name__)

# Safe defaults for the 1 GB single-VM box (Postgres max_connections=30). These
# are deliberately conservative; tune in a later change if they prove noisy.
REDIS_MEMORY_WARN_BYTES = 300 * 1024 * 1024  # 300 MB
CELERY_BACKLOG_WARN = 100  # pending tasks on the default queue
DB_CONNECTIONS_WARN = 24  # ~80% of max_connections=30

# Default Celery queue is a Redis list with this name.
_DEFAULT_QUEUE = "celery"


def _redis_client():
    import redis

    return redis.Redis.from_url(settings.CELERY_BROKER_URL)


def _redis_used_memory_bytes() -> int | None:
    try:
        return int(_redis_client().info("memory").get("used_memory", 0))
    except Exception:  # noqa: BLE001 — monitoring must never raise.
        logger.exception("metrics: failed to read Redis memory")
        return None


def _celery_backlog() -> int | None:
    try:
        return int(_redis_client().llen(_DEFAULT_QUEUE))
    except Exception:  # noqa: BLE001
        logger.exception("metrics: failed to read Celery backlog")
        return None


def _db_connection_count() -> int | None:
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE datname = current_database()"
            )
            return int(cursor.fetchone()[0])
    except Exception:  # noqa: BLE001
        logger.exception("metrics: failed to read DB connection count")
        return None


def _warn_sentry(breaches: list[str]) -> None:
    if not breaches:
        return
    try:
        import sentry_sdk
    except ImportError:
        return
    sentry_sdk.capture_message(
        "Runtime metric threshold breached: " + "; ".join(breaches),
        level="warning",
    )


@shared_task(name="apps.common.tasks.sample_system_metrics", ignore_result=True)
def sample_system_metrics() -> dict[str, int | None]:
    """Sample and log core health metrics; warn Sentry on any threshold breach."""
    redis_mem = _redis_used_memory_bytes()
    backlog = _celery_backlog()
    db_conns = _db_connection_count()

    logger.info(
        "metrics redis_used_memory_mb=%s celery_backlog=%s db_connections=%s",
        None if redis_mem is None else round(redis_mem / 1024 / 1024, 1),
        backlog,
        db_conns,
    )

    breaches: list[str] = []
    if redis_mem is not None and redis_mem > REDIS_MEMORY_WARN_BYTES:
        breaches.append(f"redis_used_memory={redis_mem} > {REDIS_MEMORY_WARN_BYTES}")
    if backlog is not None and backlog > CELERY_BACKLOG_WARN:
        breaches.append(f"celery_backlog={backlog} > {CELERY_BACKLOG_WARN}")
    if db_conns is not None and db_conns > DB_CONNECTIONS_WARN:
        breaches.append(f"db_connections={db_conns} > {DB_CONNECTIONS_WARN}")
    _warn_sentry(breaches)

    return {
        "redis_used_memory_bytes": redis_mem,
        "celery_backlog": backlog,
        "db_connections": db_conns,
    }
