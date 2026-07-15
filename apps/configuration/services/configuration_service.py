"""
Runtime configuration service.

Owns ``app_config`` and ``feature_flags``. Reads are served from a Redis cache
to keep hot values (prices, flags) off the database on every request; writes and
the scheduled refresh (Step 8) invalidate/repopulate the cache.

Values are stored as native JSON in the database. Typed accessors coerce and
supply frozen/chosen defaults when a key has not been seeded.
"""

from __future__ import annotations

import logging
from typing import Any

from django.core.cache import cache

from apps.configuration.constants import (
    APP_CONFIG_DEFAULTS,
    FEATURE_FLAG_DEFAULTS,
    AppConfigKey,
    FeatureFlagKey,
)
from apps.configuration.models import AppConfig, FeatureFlag

logger = logging.getLogger(__name__)

# Cache namespace and lifetime. The scheduled refresh (Step 8) keeps values
# fresh; the TTL is a safety net against a missed invalidation.
_CONFIG_PREFIX = "config:app:"
_FLAG_PREFIX = "config:flag:"
CACHE_TTL_SECONDS = 600

# Sentinel distinguishing "cached as absent" from a genuine cache miss.
_MISSING = "__config_missing__"


class ConfigurationService:
    """Runtime configuration and feature-flag access with caching."""

    def __init__(self, *, audit_service=None) -> None:
        self._audit_service = audit_service

    @property
    def _audit(self):
        if self._audit_service is None:
            from apps.audit.services.audit_service import AuditService

            self._audit_service = AuditService()
        return self._audit_service

    # -- Generic accessors --------------------------------------------------

    def get_config(self, key: str, default: Any = None) -> Any:
        """Return an ``app_config`` value, falling back to the seeded default."""
        cached = cache.get(_CONFIG_PREFIX + key, _MISSING)
        if cached is not _MISSING:
            return cached

        row = AppConfig.objects.filter(key=key).values_list("value", flat=True).first()
        if row is None:
            return default if default is not None else APP_CONFIG_DEFAULTS.get(key)

        cache.set(_CONFIG_PREFIX + key, row, CACHE_TTL_SECONDS)
        return row

    def get_flag(self, key: str, default: bool | None = None) -> Any:
        """Return a feature-flag value, falling back to the seeded default."""
        cached = cache.get(_FLAG_PREFIX + key, _MISSING)
        if cached is not _MISSING:
            return cached

        row = (
            FeatureFlag.objects.filter(key=key).values_list("value", flat=True).first()
        )
        if row is None:
            return default if default is not None else FEATURE_FLAG_DEFAULTS.get(key)

        cache.set(_FLAG_PREFIX + key, row, CACHE_TTL_SECONDS)
        return row

    def is_feature_enabled(self, key: str) -> bool:
        """Return whether a boolean feature flag is enabled."""
        return bool(self.get_flag(key, default=FEATURE_FLAG_DEFAULTS.get(key, False)))

    # -- Typed convenience accessors ---------------------------------------

    def get_reveal_price_paise(self) -> int:
        return int(self.get_config(AppConfigKey.REVEAL_PRICE_PAISE))

    def get_chat_extension_price_paise(self) -> int:
        return int(self.get_config(AppConfigKey.CHAT_EXTENSION_PRICE_PAISE))

    def get_matchmaking_timeout_seconds(self) -> int:
        return int(self.get_config(AppConfigKey.MATCHMAKING_TIMEOUT_SECONDS))

    def get_chat_expiry_warning_minutes(self) -> int:
        return int(self.get_config(AppConfigKey.CHAT_EXPIRY_WARNING_MINUTES))

    def get_gesture_pool(self) -> list[str]:
        return list(self.get_config(AppConfigKey.GESTURE_POOL) or [])

    def get_rating_questionnaire(self) -> dict[str, Any]:
        return dict(self.get_config(AppConfigKey.RATING_QUESTIONNAIRE) or {})

    def is_maintenance_mode(self) -> bool:
        return self.is_feature_enabled(FeatureFlagKey.MAINTENANCE_MODE)

    # -- Bulk reads (for the /config endpoint, Step 6) ---------------------

    def get_all_config(self) -> dict[str, Any]:
        """Merge seeded defaults with database overrides for every known key."""
        merged = dict(APP_CONFIG_DEFAULTS)
        merged.update({row.key: row.value for row in AppConfig.objects.all()})
        return merged

    def get_all_flags(self) -> dict[str, Any]:
        merged = dict(FEATURE_FLAG_DEFAULTS)
        merged.update({row.key: row.value for row in FeatureFlag.objects.all()})
        return merged

    def get_runtime_config(self) -> dict[str, Any]:
        """Assemble the complete runtime configuration for the /config endpoint."""
        return {
            "feature_flags": self.get_all_flags(),
            "pricing": {
                "reveal_price_paise": self.get_reveal_price_paise(),
                "chat_extension_price_paise": self.get_chat_extension_price_paise(),
            },
            "rating_questionnaire": self.get_rating_questionnaire(),
            "faq": self.get_config(AppConfigKey.FAQ_CONTENT),
            "community_guidelines": self.get_config(AppConfigKey.COMMUNITY_GUIDELINES),
            "support_email": self.get_config(AppConfigKey.SUPPORT_EMAIL),
            "app_version": {
                "minimum_supported": self.get_config(
                    AppConfigKey.MINIMUM_SUPPORTED_VERSION
                ),
                "latest": self.get_config(AppConfigKey.LATEST_VERSION),
            },
        }

    # -- Admin writes -------------------------------------------------------

    def set_flag(
        self,
        *,
        key: str,
        value: Any,
        updated_by=None,
        admin_id: str = "",
        description: str | None = None,
    ) -> FeatureFlag:
        """Upsert a feature flag, invalidate its cache, and audit the change."""
        return self._set_entry(
            model=FeatureFlag,
            prefix=_FLAG_PREFIX,
            key=key,
            value=value,
            updated_by=updated_by,
            admin_id=admin_id,
            description=description,
            entity_type="feature_flag",
        )

    def set_config(
        self,
        *,
        key: str,
        value: Any,
        updated_by=None,
        admin_id: str = "",
        description: str | None = None,
    ) -> AppConfig:
        """Upsert an app-config value, invalidate its cache, and audit."""
        return self._set_entry(
            model=AppConfig,
            prefix=_CONFIG_PREFIX,
            key=key,
            value=value,
            updated_by=updated_by,
            admin_id=admin_id,
            description=description,
            entity_type="app_config",
        )

    def _set_entry(
        self,
        *,
        model,
        prefix: str,
        key: str,
        value: Any,
        updated_by,
        admin_id: str,
        description: str | None,
        entity_type: str,
    ):
        from apps.audit.enums import ActorType

        defaults: dict[str, Any] = {"value": value, "updated_by": updated_by}
        if description is not None:
            defaults["description"] = description
        entry, _created = model.objects.update_or_create(key=key, defaults=defaults)
        cache.delete(prefix + key)
        self._audit.log(
            actor_type=ActorType.ADMIN,
            actor_id=admin_id,
            action=f"{entity_type}.updated",
            entity_type=entity_type,
            entity_id=key,
            metadata={"value": value},
        )
        return entry

    # -- Cache maintenance --------------------------------------------------

    def invalidate_config(self, key: str) -> None:
        cache.delete(_CONFIG_PREFIX + key)

    def invalidate_flag(self, key: str) -> None:
        cache.delete(_FLAG_PREFIX + key)

    def refresh_cache(self) -> None:
        """Repopulate the cache from the database for all stored keys.

        Invoked by the scheduled refresh task (Step 8) and after admin edits so
        runtime changes propagate quickly.
        """
        for row in AppConfig.objects.all():
            cache.set(_CONFIG_PREFIX + row.key, row.value, CACHE_TTL_SECONDS)
        for row in FeatureFlag.objects.all():
            cache.set(_FLAG_PREFIX + row.key, row.value, CACHE_TTL_SECONDS)
        logger.info("Configuration cache refreshed.")
