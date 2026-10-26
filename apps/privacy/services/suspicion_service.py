"""SuspicionService — orchestrates SuspicionGuard around the message pipeline.

Owns the feature flag, config-driven weights/thresholds, persistence of
``SuspicionEvent``, and the per-user ``UserSuspicionProfile`` (cumulative score,
decayed priority score, review tier, and admin review state).

This is the "second-hand Veil": it NEVER blocks, masks, or notifies the user, and
it has NO frontend presence. It only records soft signals for admin assessment and
for tuning Veil. It affects a user ONLY if an admin reviews the accumulation and
acts manually. ``MessageService`` calls :meth:`inspect` for every anonymous-phase
text message: once after Veil allows it, and once (with ``leak_blocked=True``) when
Veil hard-blocks it, so the block is recorded as the strongest soft signal.

Fail-open: any error is swallowed so a scanner bug can never break messaging.
"""

from __future__ import annotations

import logging

from django.db.models import F
from django.utils import timezone

from apps.configuration.constants import AppConfigKey, FeatureFlagKey
from apps.privacy.constants import DEFAULT_MESSAGE_WINDOW
from apps.privacy.enums import SuspicionReviewStatus, SuspicionTier
from apps.privacy.models import SuspicionEvent, UserSuspicionProfile
from apps.privacy.services.suspicion_guard import SuspicionGuard, SuspicionSignalHit
from apps.privacy.suspicion_data import (
    AMBIENT_SIGNALS,
    DEFAULT_DECAY_HALF_LIFE_DAYS,
    DEFAULT_SIGNAL_WEIGHTS,
    DEFAULT_TIER_THRESHOLDS,
    SIGNAL_CLASS,
    SUSPICION_RULE_VERSION,
)

logger = logging.getLogger(__name__)

_DEFAULT_MIN_RECORD = 2
_DEFAULT_ATTENTION = 8
_BLOCKED_LEAK = "BLOCKED_LEAK"


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
        # Merge any admin/DB overrides OVER the engine defaults, so a signal that is
        # not in a (possibly stale/partial) DB map still gets its intended weight.
        override = self._config.get_config(AppConfigKey.SUSPICION_SIGNAL_WEIGHTS)
        if isinstance(override, dict) and override:
            return {**DEFAULT_SIGNAL_WEIGHTS, **override}
        return DEFAULT_SIGNAL_WEIGHTS

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

    def _half_life_days(self) -> float:
        return float(
            self._config.get_config(AppConfigKey.SUSPICION_DECAY_HALF_LIFE_DAYS)
            or DEFAULT_DECAY_HALF_LIFE_DAYS
        )

    def _tier_thresholds(self) -> dict[str, int]:
        return (
            self._config.get_config(AppConfigKey.SUSPICION_TIER_THRESHOLDS)
            or DEFAULT_TIER_THRESHOLDS
        )

    def _window(self) -> int:
        return int(
            self._config.get_config(AppConfigKey.VEIL_MESSAGE_WINDOW)
            or DEFAULT_MESSAGE_WINDOW
        )

    # -- public API ---------------------------------------------------------
    def inspect(
        self,
        *,
        chat,
        sender,
        text: str,
        leak_blocked: bool = False,
        leak_category: str | None = None,
    ) -> None:
        """Scan one anonymous-phase message for soft signals. Returns nothing: the
        caller never acts on the result. ``leak_blocked=True`` means Veil already
        hard-blocked this message, so it is recorded as a BLOCKED_LEAK signal (the
        strongest). Fail-open."""
        if not self._enabled():
            return
        try:
            self._run(chat, sender, text, leak_blocked, leak_category)
        except Exception:
            logger.exception("Suspicion scan failed; ignoring (fail-open).")

    def _run(self, chat, sender, text, leak_blocked, leak_category) -> None:
        weights = self._weights()
        verdict = self._guard.scan(
            text,
            sender_name=getattr(sender, "full_name", "") or "",
            prior_messages=self._prior_messages(chat, sender),
            weights=weights,
        )
        hits = list(verdict.signals)
        if leak_blocked:
            hits.append(
                SuspicionSignalHit(
                    _BLOCKED_LEAK, int(weights.get(_BLOCKED_LEAK, 5)),
                    leak_category or "leak",
                )
            )

        score = sum(h.weight for h in hits)
        # Priority score EXCLUDES ambient signals (romanized Hindi / non-Latin /
        # gibberish are normal here and must never rank a legitimate user).
        priority_delta = sum(
            h.weight for h in hits if h.signal not in AMBIENT_SIGNALS
        )
        if not leak_blocked and score < self._min_record():
            return

        SuspicionEvent.objects.create(
            chat=chat,
            user=sender,
            signals=[
                {
                    "signal": h.signal,
                    "weight": h.weight,
                    "span": h.span,
                    "class": SIGNAL_CLASS.get(h.signal, "pii"),
                }
                for h in hits
            ],
            top_signal=(max(hits, key=lambda h: h.weight).signal if hits else ""),
            score=score,
            rule_version=SUSPICION_RULE_VERSION,
            raw_message=(text or "")[:4000],  # temporary: store raw for admin review
        )
        profile = self._bump_profile(sender, score, priority_delta)
        if profile.priority_score >= self._attention():
            self._raise(sender, profile.priority_score, profile.tier)

    def _prior_messages(self, chat, sender) -> tuple[str, ...]:
        """The sender's last N SENT (persisted) text messages in this chat, oldest
        first, for the behavioral (cadence / cross-message) signals."""
        from apps.messaging.enums import MessageType
        from apps.messaging.models import Message

        texts = list(
            Message.objects.filter(
                chat=chat,
                sender=sender,
                message_type=MessageType.TEXT,
                is_deleted=False,
            )
            .order_by("-created_at")
            .values_list("text_content", flat=True)[: self._window()]
        )
        texts.reverse()
        return tuple(t or "" for t in texts)

    def _tier_for(self, priority_score: int) -> str:
        t = self._tier_thresholds()
        if priority_score >= int(t.get("HIGH", 16)):
            return SuspicionTier.HIGH.value
        if priority_score >= int(t.get("ELEVATED", 8)):
            return SuspicionTier.ELEVATED.value
        if priority_score >= int(t.get("WATCH", 3)):
            return SuspicionTier.WATCH.value
        return SuspicionTier.CLEAN.value

    def _bump_profile(self, user, delta: int, priority_delta: int) -> UserSuspicionProfile:
        profile, _ = UserSuspicionProfile.objects.get_or_create(user=user)
        now = timezone.now()
        # Time-decay the existing priority score toward zero (half-life), then add the
        # new priority. Keeps the score a CURRENT-risk estimate, not a lifetime tally.
        decayed = profile.priority_score
        half_life = self._half_life_days()
        if profile.last_event_at and half_life > 0 and profile.priority_score:
            elapsed_days = (now - profile.last_event_at).total_seconds() / 86400.0
            decayed = int(round(profile.priority_score * (0.5 ** (elapsed_days / half_life))))
        new_priority = decayed + priority_delta
        tier = self._tier_for(new_priority)
        fields = {
            "score": F("score") + delta,
            "priority_score": new_priority,
            "tier": tier,
            "event_count": F("event_count") + 1,
            "last_event_at": now,
        }
        # New signals after a "cleared" verdict re-open the profile for review.
        if profile.review_status == SuspicionReviewStatus.CLEARED.value:
            fields["review_status"] = SuspicionReviewStatus.UNREVIEWED.value
        UserSuspicionProfile.objects.filter(pk=profile.pk).update(**fields)
        profile.refresh_from_db()
        return profile

    def _raise(self, user, priority_score: int, tier: str) -> None:
        from apps.audit.enums import ActorType

        self._audit.log(
            actor_type=ActorType.SYSTEM,
            action="suspicion.raised",
            entity_type="user",
            entity_id=str(user.id),
            metadata={"priority_score": priority_score, "tier": tier},
        )
