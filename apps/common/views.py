"""
Operational endpoints that are not tied to any single domain.
"""

from __future__ import annotations

from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET


@require_GET
def health_check(request: HttpRequest) -> JsonResponse:
    """Lightweight liveness probe for load balancers and uptime monitoring.

    Intentionally performs no database or cache access so it remains cheap and
    cannot be taken down by a slow dependency. The deep dependency check lives at
    ``/health/ready`` (see :func:`readiness_check`).
    """
    return JsonResponse({"status": "ok"})


@require_GET
def readiness_check(request: HttpRequest) -> JsonResponse:
    """Deep readiness probe: verifies the database and cache/broker are reachable.

    Returns 200 only when every dependency responds; 503 (with a per-check
    breakdown) otherwise, so monitoring can distinguish "process up" (``/health/``)
    from "process able to serve requests". Exposes only ok/error status, no
    internals.
    """
    from django.core.cache import cache
    from django.db import connection

    checks: dict[str, str] = {}
    healthy = True

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        checks["database"] = "ok"
    except Exception:  # noqa: BLE001 — report degraded, never 500 the probe.
        checks["database"] = "error"
        healthy = False

    try:
        cache.set("__readyz__", "1", 5)
        checks["cache"] = "ok" if cache.get("__readyz__") == "1" else "error"
        healthy = healthy and checks["cache"] == "ok"
    except Exception:  # noqa: BLE001
        checks["cache"] = "error"
        healthy = False

    return JsonResponse(
        {"status": "ok" if healthy else "degraded", "checks": checks},
        status=200 if healthy else 503,
    )
