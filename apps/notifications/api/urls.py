"""URL routes for the notifications API."""

from __future__ import annotations

from django.urls import path

from apps.notifications.api.device_views import (
    DeviceLogoutView,
    DeviceRegisterView,
)
from apps.notifications.api.views import (
    MarkAllNotificationsReadView,
    MarkNotificationReadView,
    NotificationListView,
    UnreadCountView,
)

app_name = "notifications"

urlpatterns = [
    path("notifications", NotificationListView.as_view(), name="list"),
    path(
        "notifications/unread-count",
        UnreadCountView.as_view(),
        name="unread-count",
    ),
    path(
        "notifications/read-all",
        MarkAllNotificationsReadView.as_view(),
        name="read-all",
    ),
    path(
        "notifications/<uuid:notification_id>/read",
        MarkNotificationReadView.as_view(),
        name="read",
    ),
    # Device-token registration (push). Path lives under /users/me for the
    # client's convenience; the resource is owned by the notifications domain.
    path("users/me/devices", DeviceRegisterView.as_view(), name="device-register"),
    path(
        "users/me/devices/<str:device_id>",
        DeviceLogoutView.as_view(),
        name="device-logout",
    ),
]
