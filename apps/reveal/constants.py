"""
Reveal eligibility thresholds.

See docs/REVEAL_FLOW_SPEC.md. Reveal / Safe Reveal become available once EITHER
condition holds (anti-spam gate):
    (now - chat.created_at) >= 5 minutes
    OR both users have each sent >= 5 messages
"""

from __future__ import annotations

REVEAL_ELIGIBILITY_MINUTES = 5
REVEAL_ELIGIBILITY_MESSAGES_PER_USER = 5
