"""
Cursor-based pagination matching the frozen API contract.

List endpoints accept ``?limit=&cursor=`` and return::

    {"items": [...], "next_cursor": "<opaque>" | null}

Cursor pagination (rather than offset) keeps pages stable as rows are inserted,
which matters for chronologically ordered chats and messages.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from rest_framework.pagination import CursorPagination
from rest_framework.response import Response


class StandardCursorPagination(CursorPagination):
    page_size = 20
    page_size_query_param = "limit"
    max_page_size = 100
    cursor_query_param = "cursor"
    ordering = "-created_at"

    def get_paginated_response(self, data) -> Response:
        return Response(
            {"items": data, "next_cursor": self._cursor_from_link(self.get_next_link())}
        )

    def _cursor_from_link(self, link: str | None) -> str | None:
        if not link:
            return None
        values = parse_qs(urlparse(link).query).get(self.cursor_query_param)
        return values[0] if values else None
