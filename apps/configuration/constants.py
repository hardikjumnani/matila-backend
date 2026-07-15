"""
Runtime configuration keys and their fallback defaults.

Keys mirror the ``app_config`` / ``feature_flags`` examples in the frozen
schema. Defaults let the system operate before an admin seeds configuration.

FROZEN defaults come directly from the product spec (prices in paise).
CHOSEN defaults are operational values not fixed by any frozen document; they
are safe starting points and are overridable at runtime via ``app_config``.
"""

from __future__ import annotations

from typing import Any


class AppConfigKey:
    REVEAL_PRICE_PAISE = "reveal_price_paise"
    CHAT_EXTENSION_PRICE_PAISE = "chat_extension_price_paise"
    RATING_QUESTIONNAIRE = "rating_questionnaire"
    FAQ_CONTENT = "faq_content"
    COMMUNITY_GUIDELINES = "community_guidelines"
    SUPPORT_EMAIL = "support_email"
    MINIMUM_SUPPORTED_VERSION = "minimum_supported_version"
    LATEST_VERSION = "latest_version"
    MATCHMAKING_TIMEOUT_SECONDS = "matchmaking_timeout_seconds"
    GESTURE_POOL = "gesture_pool"
    CHAT_EXPIRY_WARNING_MINUTES = "chat_expiry_warning_minutes"


class FeatureFlagKey:
    PAYMENTS_ENABLED = "payments_enabled"
    REVEAL_ENABLED = "reveal_enabled"
    IMAGE_MESSAGES_ENABLED = "image_messages_enabled"
    MAINTENANCE_MODE = "maintenance_mode"


# Fallback values used when a key has not been seeded in the database.
APP_CONFIG_DEFAULTS: dict[str, Any] = {
    AppConfigKey.REVEAL_PRICE_PAISE: 5900,  # FROZEN: reveal is Rs.59 per user.
    AppConfigKey.CHAT_EXTENSION_PRICE_PAISE: 8900,  # FROZEN: extension is Rs.89.
    AppConfigKey.MATCHMAKING_TIMEOUT_SECONDS: 300,  # CHOSEN.
    AppConfigKey.CHAT_EXPIRY_WARNING_MINUTES: 60,  # CHOSEN.
    # CHOSEN: gesture instructions the verification flow can request. gesture_type
    # on a verification request is a free string drawn from this pool.
    AppConfigKey.GESTURE_POOL: [
        "THUMBS_UP",
        "PEACE_SIGN",
        "OPEN_PALM",
        "CLOSED_FIST",
        "WAVE",
    ],
    # CHOSEN starting questionnaire; admins edit this at runtime. Answers are
    # validated against the RatingResponse value set, not this structure.
    AppConfigKey.RATING_QUESTIONNAIRE: {
        "version": "v1",
        "questions": [
            {"key": "would_chat_again", "text": "Would you chat with them again?"},
            {"key": "felt_safe", "text": "Did you feel safe during the chat?"},
            {"key": "genuine", "text": "Did the other person seem genuine?"},
        ],
    },
    AppConfigKey.SUPPORT_EMAIL: "",
    AppConfigKey.FAQ_CONTENT: [],
    AppConfigKey.COMMUNITY_GUIDELINES: "",
    AppConfigKey.MINIMUM_SUPPORTED_VERSION: "1.0.0",
    AppConfigKey.LATEST_VERSION: "1.0.0",
}

FEATURE_FLAG_DEFAULTS: dict[str, bool] = {
    FeatureFlagKey.PAYMENTS_ENABLED: True,
    FeatureFlagKey.REVEAL_ENABLED: True,
    FeatureFlagKey.IMAGE_MESSAGES_ENABLED: True,
    FeatureFlagKey.MAINTENANCE_MODE: False,
}
