"""
Celery application definition.

Task discovery, broker configuration, and the Celery Beat schedule are finalized
in Step 8 (Background Jobs). This module establishes the application instance and
autodiscovery wiring so the rest of the codebase can register tasks immediately.
"""

from __future__ import annotations

import os

from celery import Celery
from celery.signals import before_task_publish, task_postrun, task_prerun

# Celery needs a default settings module before the app is instantiated. The
# development module is the safe local default; production overrides
# DJANGO_SETTINGS_MODULE via the environment.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

app = Celery("anonymous_delayed_chat")

# All Celery configuration lives in Django settings under the CELERY_ namespace.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Discover tasks.py / tasks packages inside every installed app.
app.autodiscover_tasks()

# ---------------------------------------------------------------------------
# Request-ID correlation across the broker
# ---------------------------------------------------------------------------
# The enqueuing request's correlation id rides along in the task's message
# headers, so logs and audit rows written inside a worker trace back to the
# request that scheduled the task. In eager mode (tests) the task runs in the
# caller's context, so the ContextVar already carries the id — the handlers
# below take care not to clobber it.
_REQUEST_ID_HEADER = "request_id"


@before_task_publish.connect
def _propagate_request_id(headers=None, **_kwargs) -> None:
    """Stamp the current correlation id into the outgoing task headers."""
    from apps.common.request_id import get_request_id

    request_id = get_request_id()
    if headers is not None and request_id:
        headers[_REQUEST_ID_HEADER] = request_id


@task_prerun.connect
def _bind_request_id(task=None, **_kwargs) -> None:
    """Bind the task's correlation id for the worker's context."""
    from apps.common.request_id import get_request_id, new_request_id, set_request_id

    request = getattr(task, "request", None)
    header_id = ""
    if request is not None:
        try:
            header_id = request.get(_REQUEST_ID_HEADER) or ""
        except AttributeError:
            header_id = getattr(request, _REQUEST_ID_HEADER, "") or ""
    if header_id:
        set_request_id(header_id)
    elif not get_request_id():
        # No inbound id (e.g. a Beat-scheduled task) — mint one so the run is
        # still traceable. If the ContextVar is already set (eager), leave it.
        set_request_id(new_request_id())


@task_postrun.connect
def _clear_request_id(task=None, **_kwargs) -> None:
    """Clear the correlation id after a real worker run (never in eager mode,
    where clearing would wipe the caller's request context)."""
    from apps.common.request_id import set_request_id

    request = getattr(task, "request", None)
    if request is not None and not getattr(request, "is_eager", False):
        set_request_id("")


@app.task(bind=True, ignore_result=True)
def debug_task(self) -> None:
    """Diagnostic task used to verify worker connectivity."""
    print(f"Request: {self.request!r}")
