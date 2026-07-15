"""URL routes for the matchmaking API."""

from __future__ import annotations

from django.urls import path

from apps.matchmaking.api.views import (
    MatchmakingActiveRangeView,
    MatchmakingHeartbeatView,
    MatchmakingJoinView,
    MatchmakingLeaveView,
    MatchmakingStatusView,
)

app_name = "matchmaking"

urlpatterns = [
    path("matchmaking/join", MatchmakingJoinView.as_view(), name="join"),
    path("matchmaking/status", MatchmakingStatusView.as_view(), name="status"),
    path("matchmaking/leave", MatchmakingLeaveView.as_view(), name="leave"),
    path("matchmaking/heartbeat", MatchmakingHeartbeatView.as_view(), name="heartbeat"),
    path(
        "matchmaking/active-range",
        MatchmakingActiveRangeView.as_view(),
        name="active-range",
    ),
]
