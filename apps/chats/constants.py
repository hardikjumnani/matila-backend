"""
Chat lifecycle timing constants.

The 72-hour anonymous window is FROZEN by the product spec. The extension window
granted after a paid anonymous extension is not fixed by any frozen document; it
is a CHOSEN 2 days (48 hours) and repeats indefinitely — each extension grants
another 2-day window, after which the chat expires again and the users may
reveal, extend again, or leave (free). Revisable without a schema change.
"""

from __future__ import annotations

# FROZEN: chats stay anonymous for 72 hours before expiring.
CHAT_ANONYMOUS_WINDOW_HOURS = 72

# CHOSEN: additional anonymous time granted per paid extension (2 days), repeatable.
CHAT_EXTENSION_WINDOW_HOURS = 48
