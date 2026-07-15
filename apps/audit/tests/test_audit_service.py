"""Tests for AuditService."""

from __future__ import annotations

from django.test import TestCase

from apps.audit.enums import ActorType
from apps.audit.models import AuditLog
from apps.audit.services.audit_service import AuditService


class AuditServiceTests(TestCase):
    def setUp(self) -> None:
        self.service = AuditService()

    def test_log_creates_record(self) -> None:
        entry = self.service.log(
            actor_type=ActorType.USER,
            actor_id="user-123",
            action="chat.reported",
            entity_type="chat",
            entity_id="chat-1",
            metadata={"reason": "spam"},
            request_id="req-9",
        )
        self.assertEqual(AuditLog.objects.count(), 1)
        self.assertEqual(entry.action, "chat.reported")
        self.assertEqual(entry.metadata, {"reason": "spam"})
        self.assertEqual(entry.request_id, "req-9")

    def test_log_system_action_has_empty_actor_id(self) -> None:
        entry = self.service.log_system_action(
            action="chat.expired", entity_type="chat", entity_id="chat-2"
        )
        self.assertEqual(entry.actor_type, ActorType.SYSTEM)
        self.assertEqual(entry.actor_id, "")

    def test_log_admin_action(self) -> None:
        entry = self.service.log_admin_action(
            admin_id="7",
            action="verification.approved",
            entity_type="verification_request",
            entity_id="vr-1",
        )
        self.assertEqual(entry.actor_type, ActorType.ADMIN)
        self.assertEqual(entry.actor_id, "7")
