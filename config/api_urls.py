"""
Versioned API root (``/api/v1/``).

Each domain contributes its routes here. Step 4 wires the auth/users routes;
the remaining module routers are added in Step 6.
"""

from __future__ import annotations

from django.urls import include, path

urlpatterns = [
    path("", include("apps.users.api.urls")),
]
