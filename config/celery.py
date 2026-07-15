"""
Celery application definition.

Task discovery, broker configuration, and the Celery Beat schedule are finalized
in Step 8 (Background Jobs). This module establishes the application instance and
autodiscovery wiring so the rest of the codebase can register tasks immediately.
"""

from __future__ import annotations

import os

from celery import Celery

# Celery needs a default settings module before the app is instantiated. The
# development module is the safe local default; production overrides
# DJANGO_SETTINGS_MODULE via the environment.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

app = Celery("anonymous_delayed_chat")

# All Celery configuration lives in Django settings under the CELERY_ namespace.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Discover tasks.py / tasks packages inside every installed app.
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self) -> None:
    """Diagnostic task used to verify worker connectivity."""
    print(f"Request: {self.request!r}")
