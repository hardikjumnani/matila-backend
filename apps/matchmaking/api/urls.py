"""URL routes for the matchmaking API."""

from __future__ import annotations

from django.urls import path

from apps.matchmaking.api.views import (
    IntentStatsView,
    LobbyStatsView,
    MatchmakingHeartbeatView,
    MatchmakingJoinView,
    MatchmakingLeaveView,
    MatchmakingStatusView,
    PresenceHeartbeatView,
)

app_name = "matchmaking"

urlpatterns = [
    path("matchmaking/join", MatchmakingJoinView.as_view(), name="join"),
    path("matchmaking/status", MatchmakingStatusView.as_view(), name="status"),
    path("matchmaking/leave", MatchmakingLeaveView.as_view(), name="leave"),
    path("matchmaking/heartbeat", MatchmakingHeartbeatView.as_view(), name="heartbeat"),
    path("matchmaking/lobby-stats", LobbyStatsView.as_view(), name="lobby-stats"),
    path("matchmaking/intent-stats", IntentStatsView.as_view(), name="intent-stats"),
    path("presence/heartbeat", PresenceHeartbeatView.as_view(), name="presence-heartbeat"),
]
