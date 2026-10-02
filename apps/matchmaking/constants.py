"""Matchmaking / lobby constants. See docs/LOBBY_STATS_PLAN.md."""

from __future__ import annotations

# A user is "online" if their presence heartbeat was seen within this window.
# The app pings POST /presence/heartbeat roughly every 45s while foregrounded.
PRESENCE_ONLINE_WINDOW_SECONDS = 90

# Lobby counts are shown as coarse "N+" ranges (floor to the nearest bucket) to
# avoid exposing exact live numbers and to stop the figure flickering.
LOBBY_BUCKET_SIZE = 10
