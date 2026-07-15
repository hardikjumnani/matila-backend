"""Enumerations owned by the reports domain."""

from __future__ import annotations

from django.db import models


class ReportCategory(models.TextChoices):
    HARASSMENT = "HARASSMENT", "Harassment"
    ABUSE = "ABUSE", "Abuse"
    SPAM = "SPAM", "Spam"
    FAKE_IDENTITY = "FAKE_IDENTITY", "Fake identity"
    INAPPROPRIATE_CONTENT = "INAPPROPRIATE_CONTENT", "Inappropriate content"
    UNDERAGE = "UNDERAGE", "Underage"
    OTHER = "OTHER", "Other"


class ReportStatus(models.TextChoices):
    OPEN = "OPEN", "Open"
    UNDER_REVIEW = "UNDER_REVIEW", "Under review"
    RESOLVED = "RESOLVED", "Resolved"
    DISMISSED = "DISMISSED", "Dismissed"


class ResolutionAction(models.TextChoices):
    NONE = "NONE", "None"
    WARNING = "WARNING", "Warning"
    TEMP_SUSPENSION = "TEMP_SUSPENSION", "Temporary suspension"
    PERMANENT_BAN = "PERMANENT_BAN", "Permanent ban"
    CHAT_TERMINATED = "CHAT_TERMINATED", "Chat terminated"
    NO_ACTION = "NO_ACTION", "No action"
