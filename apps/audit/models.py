"""
Audit domain models.

``AuditLog`` is an immutable, append-only trail of significant admin, user, and
system actions. Immutability (never updated, never deleted) is enforced by
AuditService — the model stays a pure data container.

``actor_id`` is a free-form string rather than a UUID/FK because actors span
heterogeneous identity spaces: application users (UUID), admin operators (the
Django ``auth.User`` integer id), and SYSTEM actions (no actor). Storing the
identifier as text accommodates all three without a polymorphic FK.
"""

from __future__ import annotations

from django.db import models

from apps.common.models import UUIDModel

from .enums import ActorType


class AuditLog(UUIDModel):
    actor_type = models.CharField(max_length=10, choices=ActorType.choices)
    # Empty string denotes "no actor" (SYSTEM actions); text fields use "" not
    # NULL per Django convention so queries never need IS NULL handling.
    actor_id = models.CharField(max_length=64, blank=True, default="")

    action = models.CharField(max_length=100)
    entity_type = models.CharField(max_length=100)
    entity_id = models.CharField(max_length=64, blank=True, default="")

    metadata = models.JSONField(default=dict, blank=True)
    request_id = models.CharField(max_length=100, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "audit_logs"
        ordering = ["-created_at"]
        indexes = [
            # Filter by the entity a log concerns, or by the actor who acted.
            models.Index(fields=["entity_type", "entity_id"], name="idx_audit_entity"),
            models.Index(fields=["actor_type", "actor_id"], name="idx_audit_actor"),
            models.Index(fields=["action"], name="idx_audit_action"),
        ]

    def __str__(self) -> str:
        return f"AuditLog<{self.id}> {self.action} {self.entity_type}:{self.entity_id}"
