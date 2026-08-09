"""Tests for request-id correlation (middleware, logging, audit, Celery)."""

from __future__ import annotations

import logging

from celery import shared_task
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from apps.audit.enums import ActorType
from apps.audit.services.audit_service import AuditService
from apps.common import request_id as rid
from config.celery import _propagate_request_id


@shared_task
def _echo_request_id_task() -> str:
    """Test task: return whatever correlation id is bound in its context."""
    return rid.get_request_id()


class SanitizeTests(SimpleTestCase):
    def test_generates_when_absent(self) -> None:
        self.assertTrue(rid.sanitize(None))
        self.assertTrue(rid.sanitize(""))

    def test_keeps_valid_inbound(self) -> None:
        self.assertEqual(rid.sanitize("abc.DEF-123_"), "abc.DEF-123_")

    def test_strips_hostile_chars_and_caps_length(self) -> None:
        out = rid.sanitize("a b/c\n" + "x" * 200)
        self.assertNotIn(" ", out)
        self.assertNotIn("/", out)
        self.assertLessEqual(len(out), 64)


class LogFilterTests(SimpleTestCase):
    def test_injects_current_id(self) -> None:
        token = rid.set_request_id("log-rid")
        try:
            record = logging.LogRecord("x", logging.INFO, __file__, 1, "m", None, None)
            rid.RequestIDLogFilter().filter(record)
            self.assertEqual(record.request_id, "log-rid")
        finally:
            rid.reset_request_id(token)

    def test_dash_when_unset(self) -> None:
        token = rid.set_request_id("")
        try:
            record = logging.LogRecord("x", logging.INFO, __file__, 1, "m", None, None)
            rid.RequestIDLogFilter().filter(record)
            self.assertEqual(record.request_id, "-")
        finally:
            rid.reset_request_id(token)


class HttpMiddlewareTests(TestCase):
    def test_generates_and_echoes_header(self) -> None:
        response = APIClient().get("/health/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response[rid.HEADER_NAME])

    def test_echoes_valid_inbound_id(self) -> None:
        response = APIClient().get("/health/", HTTP_X_REQUEST_ID="inbound-123")
        self.assertEqual(response[rid.HEADER_NAME], "inbound-123")

    def test_sanitizes_hostile_inbound_id(self) -> None:
        response = APIClient().get("/health/", HTTP_X_REQUEST_ID="bad id/with spaces")
        self.assertNotIn(" ", response[rid.HEADER_NAME])
        self.assertNotIn("/", response[rid.HEADER_NAME])

    def test_does_not_leak_between_requests(self) -> None:
        APIClient().get("/health/", HTTP_X_REQUEST_ID="leaky")
        # After the request completes, nothing should remain bound.
        self.assertEqual(rid.get_request_id(), "")


class AuditRequestIDTests(TestCase):
    def test_log_defaults_to_contextvar(self) -> None:
        token = rid.set_request_id("audit-rid")
        try:
            entry = AuditService().log(
                actor_type=ActorType.SYSTEM, action="test.action", entity_type="thing"
            )
            self.assertEqual(entry.request_id, "audit-rid")
        finally:
            rid.reset_request_id(token)

    def test_explicit_request_id_wins(self) -> None:
        token = rid.set_request_id("ctx-rid")
        try:
            entry = AuditService().log(
                actor_type=ActorType.SYSTEM,
                action="test.action",
                entity_type="thing",
                request_id="explicit-rid",
            )
            self.assertEqual(entry.request_id, "explicit-rid")
        finally:
            rid.reset_request_id(token)


class CeleryPropagationTests(TestCase):
    def test_before_publish_attaches_header(self) -> None:
        token = rid.set_request_id("hdr-rid")
        try:
            headers: dict = {}
            _propagate_request_id(headers=headers)
            self.assertEqual(headers["request_id"], "hdr-rid")
        finally:
            rid.reset_request_id(token)

    def test_task_inherits_caller_id(self) -> None:
        token = rid.set_request_id("task-rid")
        try:
            self.assertEqual(_echo_request_id_task.apply().get(), "task-rid")
        finally:
            rid.reset_request_id(token)

    def test_task_generates_id_when_none_bound(self) -> None:
        token = rid.set_request_id("")
        try:
            self.assertTrue(_echo_request_id_task.apply().get())
        finally:
            rid.reset_request_id(token)
