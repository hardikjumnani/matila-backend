"""Django admin registration for the audit app (dev-only operator GUI).

``AuditLog`` is an immutable, append-only trail, so it is registered read-only:
no add / change / delete through the admin.
"""

from __future__ import annotations

from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "actor_type",
        "actor_id",
        "action",
        "entity_type",
        "entity_id",
        "created_at",
    )
    list_filter = ("actor_type", "action", "entity_type")
    search_fields = ("id", "actor_id", "action", "entity_type", "entity_id", "request_id")
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
