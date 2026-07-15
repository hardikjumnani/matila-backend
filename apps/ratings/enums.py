"""Enumerations owned by the ratings domain."""

from __future__ import annotations

from django.db import models


class RatingResponse(models.TextChoices):
    """Allowed answer values inside the ``responses`` JSON payload. Stored as
    JSON (the questionnaire is backend-driven and versioned), but the accepted
    values are fixed and validated by RatingService against this set."""

    YES = "YES", "Yes"
    PROBABLY_YES = "PROBABLY_YES", "Probably yes"
    PROBABLY_NO = "PROBABLY_NO", "Probably no"
    NO = "NO", "No"
