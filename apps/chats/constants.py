"""
Chat lifecycle timing constants.

The 72-hour anonymous window is FROZEN by the product spec. The extension window
granted after a paid anonymous extension is not fixed by any frozen document; it
defaults to another 72 hours (CHOSEN) and can be revisited without a schema
change.
"""

from __future__ import annotations

# FROZEN: chats stay anonymous for 72 hours before expiring.
CHAT_ANONYMOUS_WINDOW_HOURS = 72

# CHOSEN: additional anonymous time granted when both users pay to extend.
CHAT_EXTENSION_WINDOW_HOURS = 72
