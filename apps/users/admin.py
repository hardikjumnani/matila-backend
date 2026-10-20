"""Django admin registration for the users app (dev-only operator GUI)."""

from __future__ import annotations

from django.contrib import admin

from .models import User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "college_email",
        "full_name",
        "gender",
        "intent",
        "verification_status",
        "account_status",
        "college",
        "last_active_at",
    )
    list_filter = (
        "verification_status",
        "account_status",
        "gender",
        "intent",
        "college",
    )
    search_fields = ("id", "college_email", "firebase_uid", "full_name")
    raw_id_fields = ("college",)
    readonly_fields = ("created_at", "updated_at")
    ordering = ("-created_at",)
