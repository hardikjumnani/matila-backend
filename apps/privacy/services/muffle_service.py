"""MuffleService — orchestrates MuffleGuard around the message pipeline.

Owns the feature flag + shadow/mask mode, persistence of ``ProfanityEvent``, and
T2 (slur) flagging (reusing the shared ``LeakStrike`` counter). ``MessageService``
calls :meth:`inspect_and_mask` for every text message; unlike Veil it never blocks
— it returns the (possibly) masked text to persist and broadcast.

Applies in ALL chat phases (profanity is profanity before or after reveal), which
is why it is not gated on the anonymous phase the way Veil is.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.db.models import F
from django.utils import timezone

from apps.configuration.constants import AppConfigKey, FeatureFlagKey
from apps.privacy import ruleset_profanity as rp
from apps.privacy.enums import MuffleMode, ProfanityTier
from apps.privacy.models import LeakStrike, ProfanityEvent
from apps.privacy.services.muffle_guard import MuffleGuard

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MuffleOutcome:
    text: str
    changed: bool


class MuffleService:
    def __init__(self, *, configuration_service=None, guard=None) -> None:
        if configuration_service is None:
            from apps.configuration.services.configuration_service import (
                ConfigurationService,
            )

            configuration_service = ConfigurationService()
        self._config = configuration_service
        self._guard = guard or MuffleGuard()

    def _enabled(self) -> bool:
        return self._config.is_feature_enabled(FeatureFlagKey.MUFFLE_ENABLED)

    def _mode(self) -> str:
        return str(self._config.get_config(AppConfigKey.MUFFLE_MODE) or MuffleMode.MASK.value)

    def inspect_and_mask(self, *, chat, sender, text: str) -> MuffleOutcome:
        """Return the message text with harsh profanity softened. Fail-open: any
        unexpected error returns the original text rather than breaking chat."""
        if not self._enabled():
            return MuffleOutcome(text=text, changed=False)
        try:
            return self._run(chat, sender, text)
        except Exception:
            logger.exception("Muffle failed; passing message through unmasked.")
            return MuffleOutcome(text=text, changed=False)

    def _run(self, chat, sender, text: str) -> MuffleOutcome:
        result = self._guard.scan(text)
        if not result.changed:
            return MuffleOutcome(text=text, changed=False)

        mode = self._mode()
        ProfanityEvent.objects.create(
            chat=chat,
            user=sender,
            tier=result.top_tier or ProfanityTier.T1_HARSH.value,
            mode=mode,
            rule_version=rp.RULESET_VERSION,
            words=result.words,
            raw_message=(text or "")[:4000],  # temporary: store raw for admin review
            masked_message=result.masked_text[:4000],
        )

        # T2 (slur) also flags the user via the shared strike counter.
        if result.top_tier == ProfanityTier.T2_SLUR.value:
            self._bump_strike(sender)

        if mode == MuffleMode.SHADOW.value:
            return MuffleOutcome(text=text, changed=False)  # log only
        return MuffleOutcome(text=result.masked_text, changed=True)

    def _bump_strike(self, user) -> None:
        strike, _ = LeakStrike.objects.get_or_create(user=user)
        LeakStrike.objects.filter(pk=strike.pk).update(
            count=F("count") + 1, last_event_at=timezone.now()
        )
