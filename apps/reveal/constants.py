"""
Reveal eligibility thresholds (both FROZEN by the product spec).

Reveal becomes available once EITHER condition holds:
    (now - chat.created_at) >= 24 hours
    OR chat.message_count >= 100
"""

from __future__ import annotations

REVEAL_ELIGIBILITY_HOURS = 24
REVEAL_ELIGIBILITY_MESSAGE_COUNT = 100
