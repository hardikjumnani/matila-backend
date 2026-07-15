"""
Service result pattern.

Domain services never raise for *expected* business-rule failures (e.g. "chat is
read-only", "already reported"). Instead they return a ``ServiceResult`` so that
views and WebSocket consumers can translate success/failure into HTTP responses
or WebSocket error events uniformly, without try/except scattered across the
orchestration layer.

Unexpected/programming errors still raise exceptions — those are bugs, not
business outcomes, and are handled by the global exception handler (Step 6).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class ServiceResult(Generic[T]):
    """Immutable outcome of a service operation.

    Use the :meth:`ok` and :meth:`fail` constructors rather than instantiating
    directly, so the invariants (data present on success, error present on
    failure) are consistently enforced by convention.
    """

    success: bool
    data: T | None = None
    error_code: str | None = None
    error_message: str | None = None

    @classmethod
    def ok(cls, data: T | None = None) -> ServiceResult[T]:
        """Return a successful result carrying an optional payload."""
        return cls(success=True, data=data)

    @classmethod
    def fail(cls, error_code: str, error_message: str) -> ServiceResult[T]:
        """Return a failed result carrying a stable machine-readable code.

        ``error_code`` is the contract the client keys behavior on; the message
        is human-readable and must never be parsed by clients.
        """
        return cls(
            success=False,
            error_code=error_code,
            error_message=error_message,
        )

    @property
    def failed(self) -> bool:
        """True when the operation did not succeed."""
        return not self.success
