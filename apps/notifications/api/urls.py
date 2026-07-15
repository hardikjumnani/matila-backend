"""URL routes for the notifications API."""

from __future__ import annotations

from django.urls import path

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
]
