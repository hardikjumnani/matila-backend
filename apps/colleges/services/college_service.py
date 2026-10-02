"""
College service.

Resolves a user's college from their verified email domain and exposes the
launch gate used across the app. See docs/COLLEGE_LAUNCH_PLAN.md.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Count

from apps.colleges.models import College

# Code of the catch-all college for legacy/test accounts whose domain maps to no
# real college. Created by the migration + seed_colleges.
UNASSIGNED_CODE = "UNASSIGNED"


def domain_of(email: str) -> str | None:
    if not email or "@" not in email:
        return None
    return email.rsplit("@", 1)[1].strip().lower()


class CollegeService:
    def resolve_for_email(self, email: str) -> College | None:
        """The active college whose allowed domains include this email's domain,
        or None if the domain isn't supported."""
        domain = domain_of(email)
        if not domain:
            return None
        return (
            College.objects.filter(is_active=True)
            .filter(allowed_email_domains__contains=[domain])
            .first()
        )

    def is_user_launched(self, user) -> bool:
        """Whether the user's college has launched (gate for the core app)."""
        college = getattr(user, "college", None)
        return bool(college and college.is_launched)

    def launch_info(self, user) -> dict:
        """College launch state for the session / verification status payload —
        drives the FE's countdown + routing."""
        college = getattr(user, "college", None)
        if college is None:
            return {"college": None, "launched": True}
        return {
            "college": {
                "code": college.code,
                "name": college.name,
                "launch_date": (
                    college.launch_date.isoformat() if college.launch_date else None
                ),
                "launched": college.is_launched,
            },
            "launched": college.is_launched,
        }

    # -- Admin management ---------------------------------------------------

    def list_with_counts(self):
        """All colleges annotated with their member count (admin listing)."""
        return College.objects.annotate(user_count=Count("users")).order_by("name")

    def update_college(
        self,
        college: College,
        *,
        fields: dict[str, Any],
        admin_id: str = "",
    ) -> College:
        """Apply admin edits (launch_date / name / domains / is_active) and audit.

        ``allowed_email_domains`` is normalised to lowercase. Only keys present in
        ``fields`` are changed.
        """
        from apps.audit.enums import ActorType
        from apps.audit.services.audit_service import AuditService

        allowed = {"name", "launch_date", "allowed_email_domains", "is_active"}
        changed: list[str] = []
        for key, value in fields.items():
            if key not in allowed:
                continue
            if key == "allowed_email_domains" and value is not None:
                value = [str(d).strip().lower() for d in value]
            setattr(college, key, value)
            changed.append(key)
        if changed:
            college.save(update_fields=changed)
            AuditService().log(
                actor_type=ActorType.ADMIN,
                actor_id=admin_id,
                action="college.updated",
                entity_type="college",
                entity_id=str(college.id),
                metadata={
                    "fields": changed,
                    "launch_date": (
                        college.launch_date.isoformat()
                        if college.launch_date
                        else None
                    ),
                },
            )
        return college
