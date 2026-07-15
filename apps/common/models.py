"""
Reusable abstract base models.

Every table in the frozen schema uses a UUID primary key. Most, but not all,
tables also carry ``created_at``/``updated_at`` audit timestamps — some (e.g.
messages, ratings, audit logs) intentionally omit ``updated_at``. Two abstract
bases are provided so each concrete model in Step 3 inherits exactly the fields
its frozen definition requires, without forcing timestamp columns onto tables
that do not have them.
"""

from __future__ import annotations

import uuid

from django.db import models


class UUIDModel(models.Model):
    """Abstract base providing a non-editable UUID primary key."""

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    class Meta:
        abstract = True


class TimeStampedUUIDModel(UUIDModel):
    """UUID primary key plus creation and last-modified timestamps."""

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ["-created_at"]
