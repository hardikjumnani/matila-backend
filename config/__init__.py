"""
Project configuration package.

The Celery application is imported here so that it is initialized whenever Django
starts. This guarantees the shared ``@shared_task`` decorator is bound to the
configured app regardless of how the process is launched (web, worker, beat).
"""

from __future__ import annotations

from .celery import app as celery_app

__all__ = ["celery_app"]
