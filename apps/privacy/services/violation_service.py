"""ViolationReportService — records violations the FRONTEND blocked client-side.

The app's own pre-send guard stops some leak attempts before they ever reach the
backend. We still want a durable, per-person record of those attempts, so the
client reports them here. These rows are tagged ``source=FRONTEND`` and, per the
owner decision, count as real violations (they bump the shared strike counter).

The client is untrusted and spoofable, so the caller (API view) enforces auth,
participant checks, a text cap, and a per-user rate limit; ``user`` is always the
authenticated user, never client-supplied. A frontend report never auto-suspends
(escalation stays advisory, handled by admins).
"""

from __future__ import annotations

from django.db.models import F
from django.utils import timezone

from apps.common.results import ServiceResult
from apps.privacy import ruleset
from apps.privacy.enums import LeakAction, LeakCategory, LeakSeverity, ViolationSource
from apps.privacy.models import LeakEvent, LeakStrike

_VALID_CATEGORIES = set(LeakCategory.values)
_FRONTEND_MODE = "frontend"


class ViolationReportService:
    def record_frontend(
        self,
        *,
        user,
        attempted_text: str,
        category: str = "",
        chat=None,
        client_detectors: list | None = None,
    ) -> ServiceResult[LeakEvent]:
        cat = (category or "").upper()
        if cat not in _VALID_CATEGORIES:
            cat = LeakCategory.PLATFORM.value  # safe catch-all for unknown client tags

        event = LeakEvent.objects.create(
            chat=chat,
            user=user,
            category=cat,
            severity=LeakSeverity.HIGH.value,
            action=LeakAction.BLOCK.value,
            mode=_FRONTEND_MODE,
            source=ViolationSource.FRONTEND.value,
            rule_version=f"fe/{ruleset.RULESET_VERSION}",
            detectors=list(client_detectors or []),
            raw_message=(attempted_text or "")[:4000],
            matched_span="",
        )
        self._bump_strike(user)
        self._audit(user, cat)
        return ServiceResult.ok(event)

    def _bump_strike(self, user) -> None:
        strike, _ = LeakStrike.objects.get_or_create(user=user)
        LeakStrike.objects.filter(pk=strike.pk).update(
            count=F("count") + 1, last_event_at=timezone.now()
        )

    def _audit(self, user, category: str) -> None:
        from apps.audit.enums import ActorType
        from apps.audit.services.audit_service import AuditService

        AuditService().log(
            actor_type=ActorType.USER,
            actor_id=str(user.id),
            action="violation.frontend_reported",
            entity_type="user",
            entity_id=str(user.id),
            metadata={"category": category, "source": ViolationSource.FRONTEND.value},
        )
