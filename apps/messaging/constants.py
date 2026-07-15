"""
Messaging constants.

The 7-day media retention is FROZEN (images are deleted from S3 after 7 days).
The maximum text length is not fixed by any frozen document; it is a CHOSEN
guard against oversized payloads and is easily adjusted.
"""

from __future__ import annotations

# CHOSEN: maximum characters in a single text message.
MAX_TEXT_MESSAGE_LENGTH = 2000

# FROZEN: uploaded images are retained for 7 days, then deleted from storage.
MEDIA_RETENTION_DAYS = 7
