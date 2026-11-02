"""
Chat push-notification task (new message / reaction).

A push-ONLY path: unlike ``send_push_notification`` it writes no ``notifications``
inbox row (the chat + its unread count is the source of truth). It applies the
feature flag, per-chat presence suppression, and a per-(chat, recipient, kind)
cooldown, then delivers via FCM and deactivates dead tokens. Fail-open and
idempotent-ish: best-effort delivery must never affect the send path.
See docs/CHAT_PUSH_NOTIFICATIONS_PLAN.md.
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.core.cache import cache

from apps.common import firebase
from apps.common.realtime import chat_presence_key
from apps.configuration.constants import AppConfigKey, FeatureFlagKey
from apps.configuration.services.configuration_service import ConfigurationService
from apps.notifications.services.device_token_service import DeviceTokenService
from apps.users.models import User

logger = logging.getLogger(__name__)

_DEFAULT_COOLDOWN = {"message": 45, "reaction": 120}


@shared_task(bind=True, max_retries=3, default_retry_delay=30, acks_late=True)
def push_chat_event(
    self, recipient_id: str, kind: str, chat_id: str,
    title: str, body: str, data: dict | None = None,
) -> None:
    """Deliver a chat push to one recipient. ``kind`` is 'message' or 'reaction'."""
    config = ConfigurationService()
    if not config.is_feature_enabled(FeatureFlagKey.CHAT_PUSH_ENABLED):
        return
    if kind == "reaction" and not config.is_feature_enabled(
        FeatureFlagKey.CHAT_REACTION_PUSH_ENABLED
    ):
        return

    # Suppress if the recipient is currently reading THIS chat.
    if cache.get(chat_presence_key(chat_id, recipient_id)):
        return

    # Coalesce bursts: claim the cooldown slot atomically; skip if one is live.
    cooldown = _cooldown_seconds(config, kind)
    slot = f"chatpush:{kind}:{chat_id}:{recipient_id}"
    if cooldown > 0 and not cache.add(slot, "1", cooldown):
        return

    user = User.objects.filter(id=recipient_id).first()
    if user is None:
        return
    tokens = list(
        DeviceTokenService().active_tokens_for(user).values_list("token", flat=True)
    )
    if not tokens:
        return

    try:
        result = firebase.send_push(
            tokens, title=title, body=body, data=data or {},
            collapse_key=f"chat-{chat_id}",
        )
    except firebase.FirebaseNotConfigured:
        return  # No credentials in this environment — skip, do not retry.
    except Exception as exc:  # noqa: BLE001 — transient FCM/network failure.
        logger.warning("Chat push failed for recipient %s: %s", recipient_id, exc)
        raise self.retry(exc=exc) from exc

    if result.invalid_tokens:
        DeviceTokenService().deactivate_tokens(result.invalid_tokens)


def _cooldown_seconds(config: ConfigurationService, kind: str) -> int:
    key = (
        AppConfigKey.CHAT_REACTION_PUSH_COOLDOWN_SECONDS
        if kind == "reaction"
        else AppConfigKey.CHAT_PUSH_COOLDOWN_SECONDS
    )
    try:
        return int(config.get_config(key) or _DEFAULT_COOLDOWN.get(kind, 45))
    except (TypeError, ValueError):
        return _DEFAULT_COOLDOWN.get(kind, 45)
