"""VeilService — orchestrates the Veil engine around LeakGuard.

Owns everything the pure scanner cannot: the feature flag + shadow/enforce mode,
the cross-message window (the sender's last N SENT messages, read from the DB),
persistence of ``LeakEvent``, the per-user strike counter, escalation, and the
graduated block message.

``MessageService`` calls :meth:`inspect_text` for every text message sent during
the ANONYMOUS phase of a chat.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass

from django.db.models import F
from django.utils import timezone

from apps.configuration.constants import AppConfigKey, FeatureFlagKey
from apps.privacy import ruleset
from apps.privacy.constants import (
    DEFAULT_ESCALATE_THRESHOLD,
    DEFAULT_MESSAGE_WINDOW,
    MAX_ACCUMULATED_DIGITS,
    MAX_WINDOW_CHARS,
)
from apps.privacy.enums import LeakAction, LeakCategory, VeilMode
from apps.privacy.models import LeakEvent, LeakStrike
from apps.privacy.services.leakguard import LeakGuard, Verdict, extract_digits

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class VeilDecision:
    blocked: bool
    user_message: str = ""
    action: str | None = None
    category: str | None = None


class VeilService:
    def __init__(
        self,
        *,
        configuration_service=None,
        notification_service=None,
        audit_service=None,
        guard=None,
    ) -> None:
        if configuration_service is None:
            from apps.configuration.services.configuration_service import (
                ConfigurationService,
            )

            configuration_service = ConfigurationService()
        self._config = configuration_service
        self._notification_service = notification_service
        self._audit_service = audit_service
        self._guard = guard or LeakGuard()

    # -- lazy collaborators (avoid import cycles / unused wiring) ------------
    @property
    def _notifications(self):
        if self._notification_service is None:
            from apps.notifications.services.notification_service import (
                NotificationService,
            )

            self._notification_service = NotificationService()
        return self._notification_service

    @property
    def _audit(self):
        if self._audit_service is None:
            from apps.audit.services.audit_service import AuditService

            self._audit_service = AuditService()
        return self._audit_service

    # -- config accessors ---------------------------------------------------
    def _enabled(self) -> bool:
        return self._config.is_feature_enabled(FeatureFlagKey.VEIL_ENABLED)

    def _mode(self) -> str:
        return str(self._config.get_config(AppConfigKey.VEIL_MODE) or VeilMode.ENFORCE.value)

    def _message_window(self) -> int:
        """Cross-message window size = the sender's last N SENT messages."""
        return int(
            self._config.get_config(AppConfigKey.VEIL_MESSAGE_WINDOW)
            or DEFAULT_MESSAGE_WINDOW
        )

    def _escalate_threshold(self) -> int:
        return int(
            self._config.get_config(AppConfigKey.VEIL_ESCALATE_THRESHOLD)
            or DEFAULT_ESCALATE_THRESHOLD
        )

    # -- public API ---------------------------------------------------------
    def inspect_text(self, *, chat, sender, text: str) -> VeilDecision:
        """Scan one outgoing text message. Returns a decision the caller acts on.

        In ``shadow`` mode a block-worthy message is recorded but still allowed
        (for tuning); in ``enforce`` mode it is blocked, strikes are counted, and
        repeat offenders are escalated.

        Fail-open: any unexpected error allows the message rather than breaking
        chat — a scanner bug must never take messaging down.
        """
        if not self._enabled():
            return VeilDecision(blocked=False)
        try:
            return self._inspect(chat, sender, text)
        except Exception:
            logger.exception("Veil inspection failed; allowing message (fail-open).")
            return VeilDecision(blocked=False)

    def _inspect(self, chat, sender, text: str) -> VeilDecision:
        prior_text, prior_digits = self._build_window(chat, sender)
        verdict = self._guard.scan(
            text,
            prior_digits=prior_digits,
            prior_text=prior_text,
            sender_name=getattr(sender, "full_name", "") or "",
        )

        if not verdict.blocked:
            return VeilDecision(blocked=False)

        mode = self._mode()
        if mode == VeilMode.SHADOW.value:
            self._record_event(chat, sender, verdict, LeakAction.BLOCK.value, mode, text)
            return VeilDecision(blocked=False)

        # Enforce.
        strike = self._bump_strike(sender)
        action = (
            LeakAction.ESCALATE.value
            if strike.count >= self._escalate_threshold()
            else LeakAction.BLOCK.value
        )
        self._record_event(chat, sender, verdict, action, mode, text)
        if action == LeakAction.ESCALATE.value:
            self._escalate(sender, strike.count, verdict)

        return VeilDecision(
            blocked=True,
            user_message=self._message_for(verdict, strike.count),
            action=action,
            category=verdict.top_category,
        )

    def _build_window(self, chat, sender) -> tuple[str, str]:
        """Cross-message window from the sender's last N SENT (persisted) text
        messages in this chat. A blocked attempt is never persisted, so it cannot
        enter the window. Returns (prior_text, prior_digits)."""
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
            .values_list("text_content", flat=True)[: self._message_window()]
        )
        texts.reverse()  # chronological
        prior_text = " ".join(t for t in texts if t)[-MAX_WINDOW_CHARS:]
        prior_digits = extract_digits(prior_text)[-MAX_ACCUMULATED_DIGITS:]
        return prior_text, prior_digits

    # -- internals ----------------------------------------------------------
    def _bump_strike(self, user) -> LeakStrike:
        strike, _ = LeakStrike.objects.get_or_create(user=user)
        LeakStrike.objects.filter(pk=strike.pk).update(
            count=F("count") + 1, last_event_at=timezone.now()
        )
        strike.refresh_from_db()
        return strike

    def _record_event(
        self, chat, sender, verdict: Verdict, action: str, mode: str, raw_text: str
    ) -> None:
        matched = "; ".join(h.span for h in verdict.hits if h.span)[:500]
        LeakEvent.objects.create(
            chat=chat,
            user=sender,
            category=verdict.top_category or LeakCategory.PLATFORM.value,
            severity=verdict.top_severity or "",
            action=action,
            mode=mode,
            rule_version=ruleset.RULESET_VERSION,
            detectors=verdict.detectors,
            raw_message=(raw_text or "")[:4000],  # temporary: store raw for admin review
            matched_span=matched,
        )

    def _escalate(self, user, count: int, verdict: Verdict) -> None:
        from apps.audit.enums import ActorType

        self._audit.log(
            actor_type=ActorType.SYSTEM,
            action="veil.escalated",
            entity_type="user",
            entity_id=str(user.id),
            metadata={"count": count, "category": verdict.top_category},
        )
        try:
            self._notifications.create_notification(
                user=user,
                type="veil.warning",
                title="Please keep it in Matila",
                body=self._message_for(verdict, count),
                action_type="OPEN_CHAT",
                action_payload={},
            )
        except Exception:  # notifications must never block message handling
            logger.exception("Veil escalation notification failed for user %s", user.id)

    # First-offence, category-specific nudges (gentler + more precise than the
    # generic ladder). Repeat offences fall through to the graduated ladder.
    _CATEGORY_TONES = {
        LeakCategory.SOLICITATION.value: "ask",
        LeakCategory.MEETING.value: "meet",
        LeakCategory.SELF_NAME.value: "name",
    }

    def _message_for(self, verdict: Verdict, count: int) -> str:
        if count <= 1:
            tone = self._CATEGORY_TONES.get(verdict.top_category)
            if tone is not None:
                return random.choice(ruleset.TONES[tone])
            tone = "gentle"
        elif count == 2:
            tone = "firm"
        else:
            tone = "serious"
        return random.choice(ruleset.TONES[tone])
