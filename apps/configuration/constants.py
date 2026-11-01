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

# Single source of truth for the suspicion engine's weights / decay / tiers lives
# with the engine data (pure module, no Django imports), so config can never drift.
from apps.privacy.suspicion_data import (
    DEFAULT_DECAY_HALF_LIFE_DAYS as _SUSPICION_HALF_LIFE,
    DEFAULT_SIGNAL_WEIGHTS as _SUSPICION_WEIGHTS,
    DEFAULT_TIER_THRESHOLDS as _SUSPICION_TIERS,
)


class AppConfigKey:
    # Direct-cash prices (paise) per action side.
    REVEAL_PRICE_PAISE = "reveal_price_paise"
    SAFE_REVEAL_FEMALE_PRICE_PAISE = "safe_reveal_female_price_paise"
    SAFE_REVEAL_MALE_PRICE_PAISE = "safe_reveal_male_price_paise"
    CHAT_EXTENSION_PRICE_PAISE = "chat_extension_price_paise"
    # Coin costs per action side (unified Coin).
    COIN_COST_REVEAL = "coin_cost_reveal"
    # Discounted price for a user's VERY FIRST full reveal (one-time, per user).
    # See docs/FIRST_REVEAL_DISCOUNT_PLAN.md.
    COIN_COST_REVEAL_FIRST = "coin_cost_reveal_first"
    COIN_COST_SAFE_REVEAL_MALE = "coin_cost_safe_reveal_male"
    COIN_COST_SAFE_REVEAL_FEMALE = "coin_cost_safe_reveal_female"
    COIN_COST_EXTEND = "coin_cost_extend"
    # Store coin packs.
    COIN_PACKS = "coin_packs"
    RATING_QUESTIONNAIRE = "rating_questionnaire"
    FAQ_CONTENT = "faq_content"
    COMMUNITY_GUIDELINES = "community_guidelines"
    SUPPORT_EMAIL = "support_email"
    MINIMUM_SUPPORTED_VERSION = "minimum_supported_version"
    LATEST_VERSION = "latest_version"
    MATCHMAKING_TIMEOUT_SECONDS = "matchmaking_timeout_seconds"
    GESTURE_POOL = "gesture_pool"
    CHAT_EXPIRY_WARNING_MINUTES = "chat_expiry_warning_minutes"
    # Emoji set for message reactions (runtime-editable, like the gesture pool).
    REACTION_EMOJIS = "reaction_emojis"
    # Veil (anti-leakage) engine, see docs/VEIL_ENGINE_PLAN.md.
    VEIL_MODE = "veil_mode"  # "shadow" | "enforce"
    VEIL_WINDOW_SECONDS = "veil_window_seconds"  # legacy (time window); superseded
    VEIL_MESSAGE_WINDOW = "veil_message_window"  # cross-message window = last N msgs
    VEIL_ESCALATE_THRESHOLD = "veil_escalate_threshold"
    # Muffle (profanity softening) engine, see docs/MUFFLE_PROFANITY_PLAN.md.
    MUFFLE_MODE = "muffle_mode"  # "shadow" | "mask"
    # Suspicion engine (second-hand Veil, non-blocking soft signals). See
    # docs/VEIL_VIOLATION_TRACKING_AND_SUSPICION_PLAN.md.
    SUSPICION_SIGNAL_WEIGHTS = "suspicion_signal_weights"  # {signal: weight}
    SUSPICION_MIN_RECORD_WEIGHT = "suspicion_min_record_weight"  # skip trivial noise
    SUSPICION_ATTENTION_SCORE = "suspicion_attention_score"  # per-user audit threshold
    SUSPICION_DECAY_HALF_LIFE_DAYS = "suspicion_decay_half_life_days"  # priority decay
    SUSPICION_TIER_THRESHOLDS = "suspicion_tier_thresholds"  # {WATCH, ELEVATED, HIGH}


class FeatureFlagKey:
    PAYMENTS_ENABLED = "payments_enabled"
    REVEAL_ENABLED = "reveal_enabled"
    IMAGE_MESSAGES_ENABLED = "image_messages_enabled"
    MAINTENANCE_MODE = "maintenance_mode"
    VEIL_ENABLED = "veil_enabled"
    MUFFLE_ENABLED = "muffle_enabled"
    # Second-hand Veil suspicion engine (non-blocking). Seeded OFF; tune then on.
    SUSPICION_ENABLED = "suspicion_enabled"
    # One-time first-reveal coin discount (coin_cost_reveal_first). ON by default.
    FIRST_REVEAL_DISCOUNT_ENABLED = "first_reveal_discount_enabled"
    # Direct cash-per-action purchase (Google Play verify-purchase for
    # reveal/safe-reveal/extend). Seeded OFF: the app is coins-only, so a paid
    # action is funded by buying a coin pack and spending coins. Flip on only to
    # restore the two-tier (coins OR direct cash) model. See docs/COINS_ONLY_PLAN.md.
    DIRECT_ACTION_PURCHASE_ENABLED = "direct_action_purchase_enabled"


# Fallback values used when a key has not been seeded in the database.
APP_CONFIG_DEFAULTS: dict[str, Any] = {
    # FINAL direct-cash prices (paise). Coins are the cheaper path; these are the
    # pay-direct amounts shown to users who do not use coins.
    AppConfigKey.REVEAL_PRICE_PAISE: 7000,  # Rs.70 reveal.
    AppConfigKey.SAFE_REVEAL_FEMALE_PRICE_PAISE: 10000,  # Rs.100 safe reveal, girl.
    AppConfigKey.SAFE_REVEAL_MALE_PRICE_PAISE: 5000,  # Rs.50 safe reveal, boy.
    AppConfigKey.CHAT_EXTENSION_PRICE_PAISE: 5000,  # Rs.50 extend.
    # FINAL coin costs per action side (unified Coin).
    AppConfigKey.COIN_COST_REVEAL: 10,
    AppConfigKey.COIN_COST_REVEAL_FIRST: 8,  # one-time first-reveal discount.
    AppConfigKey.COIN_COST_SAFE_REVEAL_MALE: 8,
    AppConfigKey.COIN_COST_SAFE_REVEAL_FEMALE: 16,
    AppConfigKey.COIN_COST_EXTEND: 6,
    # FINAL store coin packs (paise). price_paise is charged; original_price_paise
    # drives the struck-through cut. sku must match the Google Play managed-product id.
    AppConfigKey.COIN_PACKS: [
        {"sku": "coin_pack_10", "coins": 10, "price_paise": 5900, "original_price_paise": 7000},
        {"sku": "coin_pack_30", "coins": 30, "price_paise": 14900, "original_price_paise": 21000},
        {"sku": "coin_pack_50", "coins": 50, "price_paise": 22400, "original_price_paise": 35000},
        {"sku": "coin_pack_100", "coins": 100, "price_paise": 42900, "original_price_paise": 70000},
    ],
    AppConfigKey.MATCHMAKING_TIMEOUT_SECONDS: 300,  # CHOSEN.
    AppConfigKey.CHAT_EXPIRY_WARNING_MINUTES: 60,  # CHOSEN.
    # CHOSEN: message-reaction emoji set (runtime-editable; the FE bundles the
    # same default and falls back to it offline). Served via GET /config.
    AppConfigKey.REACTION_EMOJIS: ["❤️", "\U0001F602", "\U0001F62E",
                                   "\U0001F622", "\U0001F44D", "\U0001F525"],
    # CHOSEN: Veil anti-leakage engine. Mode starts at "enforce" so the control
    # is active in dev; production should run "shadow" first to tune (see plan).
    AppConfigKey.VEIL_MODE: "enforce",
    AppConfigKey.VEIL_WINDOW_SECONDS: 120,  # legacy (time window); superseded.
    AppConfigKey.VEIL_MESSAGE_WINDOW: 8,  # cross-message window = last N sent msgs.
    AppConfigKey.VEIL_ESCALATE_THRESHOLD: 5,  # blocks before T&S escalation.
    # CHOSEN: Muffle profanity softener. "mask" is active in dev; production may
    # start "shadow" to tune the tier boundary first (see plan).
    AppConfigKey.MUFFLE_MODE: "mask",
    # CHOSEN: Suspicion engine (second-hand Veil). Non-blocking; records soft
    # signals for admin review. Per-signal weights + record/attention thresholds
    # are runtime-tunable so the admin feed can be kept usable without a deploy.
    # Weights, decay and tier thresholds come from the engine's single source of
    # truth (apps/privacy/suspicion_data.py) so the two can never drift.
    AppConfigKey.SUSPICION_SIGNAL_WEIGHTS: dict(_SUSPICION_WEIGHTS),
    AppConfigKey.SUSPICION_MIN_RECORD_WEIGHT: 2,
    AppConfigKey.SUSPICION_ATTENTION_SCORE: 8,
    AppConfigKey.SUSPICION_DECAY_HALF_LIFE_DAYS: _SUSPICION_HALF_LIFE,
    AppConfigKey.SUSPICION_TIER_THRESHOLDS: dict(_SUSPICION_TIERS),
    # CHOSEN: gesture instructions the verification flow can request. Each entry is
    # {code, label, emoji}: the CODE is stored on verification_requests.gesture_type
    # (stable identifier); label + emoji are presentation, served to the client so
    # gestures can be added/relabelled at runtime with no app release. Runtime
    # editable via the admin app-config (validated in validators.py).
    AppConfigKey.GESTURE_POOL: [
        {"code": "CALL_ME", "label": "Swag", "emoji": "\U0001F919"},
        {"code": "LOVE_YOU_SIGN", "label": "Love-you sign", "emoji": "\U0001F91F"},
        {"code": "ROCK_ON", "label": "Rock on", "emoji": "\U0001F918"},
        {"code": "OK_SIGN", "label": "OK sign", "emoji": "\U0001F44C"},
        {"code": "CROSSED_FINGERS", "label": "Crossed fingers", "emoji": "\U0001F91E"},
        {"code": "FINGER_HEART", "label": "Finger heart", "emoji": "\U0001FAF0"},
        {"code": "PINCHED_FINGERS", "label": "Pinched fingers", "emoji": "\U0001F90C"},
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
    FeatureFlagKey.VEIL_ENABLED: True,
    FeatureFlagKey.MUFFLE_ENABLED: True,
    FeatureFlagKey.SUSPICION_ENABLED: False,  # OFF by default; tune then enable.
    # One-time first-reveal coin discount. ON by default; runtime kill-switch.
    FeatureFlagKey.FIRST_REVEAL_DISCOUNT_ENABLED: True,
    # OFF by default: coins-only. Direct cash-per-action is retired; funding an
    # action means buying a coin pack then spending coins. See COINS_ONLY_PLAN.md.
    FeatureFlagKey.DIRECT_ACTION_PURCHASE_ENABLED: False,
}
