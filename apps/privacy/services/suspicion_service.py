"""SuspicionService — orchestrates SuspicionGuard around the message pipeline.

Owns the feature flag, config-driven weights/thresholds, persistence of
``SuspicionEvent``, and the per-user ``UserSuspicionProfile`` (cumulative score +
admin review state). ``MessageService`` calls :meth:`inspect` for every text
message sent during the ANONYMOUS phase, right after Veil allows it.

This is the "second-hand Veil": it NEVER blocks, masks, or notifies the user. It
only records soft signals for admin assessment and for tuning Veil. Fail-open:
any error is swallowed so a scanner bug can never break messaging.
"""

from __future__ import annotations

import logging

from django.db.models import F
from django.utils import timezone

from apps.configuration.constants import AppConfigKey, FeatureFlagKey
from apps.privacy.enums import SuspicionReviewStatus
from apps.privacy.models import SuspicionEvent, UserSuspicionProfile
from apps.privacy.services.suspicion_guard import SuspicionGuard
from apps.privacy.suspicion_data import (
    DEFAULT_SIGNAL_WEIGHTS,
    SUSPICION_RULE_VERSION,
)

logger = logging.getLogger(__name__)

_DEFAULT_MIN_RECORD = 2
_DEFAULT_ATTENTION = 8


class SuspicionService:
    def __init__(
        self, *, configuration_service=None, guard=None, audit_service=None
    ) -> None:
        if configuration_service is None:
            from apps.configuration.services.configuration_service import (
                ConfigurationService,
            )

            configuration_service = ConfigurationService()
        self._config = configuration_service
        self._audit_service = audit_service
        self._guard = guard or SuspicionGuard()

    @property
    def _audit(self):
        if self._audit_service is None:
            from apps.audit.services.audit_service import AuditService

            self._audit_service = AuditService()
        return self._audit_service

    # -- config accessors ---------------------------------------------------
    def _enabled(self) -> bool:
        return self._config.is_feature_enabled(FeatureFlagKey.SUSPICION_ENABLED)

    def _weights(self) -> dict[str, int]:
        return (
            self._config.get_config(AppConfigKey.SUSPICION_SIGNAL_WEIGHTS)
            or DEFAULT_SIGNAL_WEIGHTS
        )

    def _min_record(self) -> int:
        return int(
            self._config.get_config(AppConfigKey.SUSPICION_MIN_RECORD_WEIGHT)
            or _DEFAULT_MIN_RECORD
        )

    def _attention(self) -> int:
        return int(
            self._config.get_config(AppConfigKey.SUSPICION_ATTENTION_SCORE)
            or _DEFAULT_ATTENTION
        )

    # -- public API ---------------------------------------------------------
    def inspect(self, *, chat, sender, text: str) -> None:
        """Scan one outgoing (already-allowed) message for soft signals. Returns
        nothing: the caller never acts on the result. Fail-open."""
        if not self._enabled():
            return
        try:
            self._run(chat, sender, text)
        except Exception:
            logger.exception("Suspicion scan failed; ignoring (fail-open).")

    def _run(self, chat, sender, text: str) -> None:
        verdict = self._guard.scan(
            text,
            sender_name=getattr(sender, "full_name", "") or "",
            weights=self._weights(),
        )
        if verdict.score < self._min_record():
            return

        SuspicionEvent.objects.create(
            chat=chat,
            user=sender,
            signals=[
                {"signal": h.signal, "weight": h.weight, "span": h.span}
                for h in verdict.signals
            ],
            top_signal=verdict.top_signal or "",
            score=verdict.score,
            rule_version=SUSPICION_RULE_VERSION,
            raw_message=(text or "")[:4000],  # temporary: store raw for admin review
        )
        profile = self._bump_profile(sender, verdict.score)
        if profile.score >= self._attention():
            self._raise(sender, profile.score, verdict.top_signal)

    def _bump_profile(self, user, delta: int) -> UserSuspicionProfile:
        profile, _ = UserSuspicionProfile.objects.get_or_create(user=user)
        fields = {
            "score": F("score") + delta,
            "event_count": F("event_count") + 1,
            "last_event_at": timezone.now(),
        }
        # New signals after a "cleared" verdict re-open the profile for review.
        if profile.review_status == SuspicionReviewStatus.CLEARED.value:
            fields["review_status"] = SuspicionReviewStatus.UNREVIEWED.value
        UserSuspicionProfile.objects.filter(pk=profile.pk).update(**fields)
        profile.refresh_from_db()
        return profile

    def _raise(self, user, score: int, top_signal: str | None) -> None:
        from apps.audit.enums import ActorType

        self._audit.log(
            actor_type=ActorType.SYSTEM,
            action="suspicion.raised",
            entity_type="user",
            entity_id=str(user.id),
            metadata={"score": score, "top_signal": top_signal},
        )
