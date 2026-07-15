"""
Domain exception hierarchy.

These represent *unexpected* failures or hard invariants that should abort the
current operation (as opposed to expected business outcomes, which flow through
``ServiceResult``). The custom DRF exception handler (Step 6) maps these to the
standardized error envelope defined in API_DESIGN.md.

Error codes mirror the "Common Error Codes" table in API_DESIGN.md so the client
contract stays consistent across the whole surface.
"""

from __future__ import annotations


class DomainError(Exception):
    """Base class for all domain-level errors.

    Carries a stable ``code`` (client contract) and a human-readable
    ``message``. Subclasses set sensible defaults; call sites may override.
    """

    default_code: str = "INTERNAL_SERVER_ERROR"
    default_message: str = "An unexpected error occurred."

    def __init__(self, message: str | None = None, code: str | None = None) -> None:
        self.code = code or self.default_code
        self.message = message or self.default_message
        super().__init__(self.message)


class ValidationError(DomainError):
    """Input failed a domain-level validation rule."""

    default_code = "VALIDATION_ERROR"
    default_message = "The provided data is invalid."


class NotFoundError(DomainError):
    """A requested resource does not exist or is not visible to the caller."""

    default_code = "RESOURCE_NOT_FOUND"
    default_message = "The requested resource was not found."


class PermissionDeniedError(DomainError):
    """The caller is authenticated but not permitted to perform the action."""

    default_code = "FORBIDDEN"
    default_message = "You do not have permission to perform this action."


class ConflictError(DomainError):
    """The operation conflicts with the current state of the resource."""

    default_code = "CONFLICT"
    default_message = "The request conflicts with the current resource state."
