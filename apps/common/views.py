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
    cannot be taken down by a slow dependency. Deep dependency health checks are
    added with monitoring in Step 11.
    """
    return JsonResponse({"status": "ok"})
