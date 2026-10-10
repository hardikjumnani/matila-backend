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
DEFAULT_WINDOW_SECONDS = 120
DEFAULT_ESCALATE_THRESHOLD = 5
