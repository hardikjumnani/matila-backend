"""Django admin registration for the verification app (dev-only operator GUI)."""

from __future__ import annotations

from django.contrib import admin

from .models import VerificationRequest


@admin.register(VerificationRequest)
class VerificationRequestAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "attempt_number",
        "status",
        "gesture_type",
        "submitted_at",
        "reviewed_at",
        "reviewed_by",
    )
    list_filter = ("status",)
    search_fields = ("id", "user__id", "user__college_email")
    raw_id_fields = ("user", "reviewed_by")
    readonly_fields = ("created_at", "updated_at")
    ordering = ("-created_at",)
