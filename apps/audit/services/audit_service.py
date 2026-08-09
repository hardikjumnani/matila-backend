"""
Audit trail service.

Owns ``audit_logs``. The table is append-only and immutable: this service only
ever creates rows — it exposes no update or delete operation, which is how the
immutability guarantee is enforced (per the agreed approach: in the service, not
via database triggers).
"""

from __future__ import annotations

import logging
from typing import Any

from apps.audit.enums import ActorType
from apps.audit.models import AuditLog
from apps.common.request_id import get_request_id

logger = logging.getLogger(__name__)


class AuditService:
    """Record immutable audit events for admin, user, and system actions."""

    def log(
        self,
        *,
        actor_type: ActorType | str,
        action: str,
        entity_type: str,
        entity_id: str = "",
        actor_id: str = "",
        metadata: dict[str, Any] | None = None,
        request_id: str = "",
    ) -> AuditLog:
        """Append a single audit record.

        Args:
            actor_type: who acted (ADMIN, USER, or SYSTEM).
            action: dotted action key, e.g. "verification.approved".
            entity_type: the kind of entity affected, e.g. "user".
            entity_id: the affected entity's identifier (stringified UUID/pk).
            actor_id: the actor's identifier ("" for SYSTEM).
            metadata: structured context; never contains secrets or tokens.
            request_id: correlation id tying the event to a request; falls back
                to the current request's id (from the ContextVar) when omitted.
        """
        return AuditLog.objects.create(
            actor_type=actor_type,
            actor_id=str(actor_id) if actor_id else "",
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id else "",
            metadata=metadata or {},
            request_id=request_id or get_request_id(),
        )

    def log_admin_action(
        self,
        *,
        admin_id: str,
        action: str,
        entity_type: str,
        entity_id: str = "",
        metadata: dict[str, Any] | None = None,
        request_id: str = "",
    ) -> AuditLog:
        return self.log(
            actor_type=ActorType.ADMIN,
            actor_id=admin_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            metadata=metadata,
            request_id=request_id,
        )

    def log_system_action(
        self,
        *,
        action: str,
        entity_type: str,
        entity_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> AuditLog:
        return self.log(
            actor_type=ActorType.SYSTEM,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            metadata=metadata,
        )
