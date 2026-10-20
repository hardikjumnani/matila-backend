"""Veil constants: cache keys and chosen operational defaults."""

from __future__ import annotations

# Rolling per-(chat, sender) digit accumulator for the Number Reassembler.
DIGIT_WINDOW_CACHE_PREFIX = "veil:digits:"
# Cap the accumulator so it can only ever form ~one phone number of context.
MAX_ACCUMULATED_DIGITS = 32

# Rolling per-(chat, sender) text window for cross-message keyword/phrase leaks
# (e.g. "add me" then "on insta"). Capped so only a short span is reconstructed.
TEXT_WINDOW_CACHE_PREFIX = "veil:text:"
MAX_WINDOW_CHARS = 240

# CHOSEN defaults (overridable at runtime via app_config).
DEFAULT_WINDOW_SECONDS = 120  # legacy (time window); superseded by the message window.
# Cross-message window is now the sender's last N SENT messages (count-based, not
# time-based). Derived from persisted messages, so a blocked (unpersisted) attempt
# never enters the window. See docs/VEIL_V2_PLAN.md.
DEFAULT_MESSAGE_WINDOW = 8
DEFAULT_ESCALATE_THRESHOLD = 5
