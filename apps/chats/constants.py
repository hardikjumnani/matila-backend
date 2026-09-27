"""
Chat lifecycle timing constants.

See docs/REVEAL_FLOW_SPEC.md (source of truth). The anonymous window is a CHOSEN
48 hours; each paid extension grants another 48h and repeats indefinitely. After
the window expires the chat enters a 24h decision grace period, after which an
undecided/incomplete chat auto-exits. All revisable without a schema change.
"""

from __future__ import annotations

# CHOSEN: chats stay anonymous for 48 hours before expiring.
CHAT_ANONYMOUS_WINDOW_HOURS = 48

# CHOSEN: additional anonymous time granted per paid extension (2 days), repeatable.
CHAT_EXTENSION_WINDOW_HOURS = 48

# CHOSEN: after expiry, users have this long to complete a decision before the
# chat auto-exits (end + release + feedback). Server-authoritative.
DECISION_GRACE_HOURS = 24
