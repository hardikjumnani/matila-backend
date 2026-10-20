"""
Validation for admin-edited pricing config.

The admin app-config PUT endpoint accepts raw JSON, so pricing keys need guarding
before they are stored (a bad price or a broken coin-pack list would otherwise go
live). These rules run at the admin API boundary only; internal writers (seed, code
defaults) are trusted. See docs/COIN_REWORK_PLAN.md and EXTERNAL_BRIDGE A0001.
"""

from __future__ import annotations

from apps.configuration.constants import APP_CONFIG_DEFAULTS, AppConfigKey

# Scalar keys that must be a positive integer.
_POSITIVE_INT_KEYS = {
    AppConfigKey.REVEAL_PRICE_PAISE,
    AppConfigKey.CHAT_EXTENSION_PRICE_PAISE,
    AppConfigKey.SAFE_REVEAL_FEMALE_PRICE_PAISE,
    AppConfigKey.SAFE_REVEAL_MALE_PRICE_PAISE,
    AppConfigKey.COIN_COST_REVEAL,
    AppConfigKey.COIN_COST_SAFE_REVEAL_MALE,
    AppConfigKey.COIN_COST_SAFE_REVEAL_FEMALE,
    AppConfigKey.COIN_COST_EXTEND,
}

# The fixed set of coin-pack SKUs (each maps to a Google Play managed product).
# Admins may edit a pack's coins/prices but may not add, remove, rename, or
# duplicate SKUs; that is a code + Play Console change.
_EXPECTED_PACK_SKUS = tuple(p["sku"] for p in APP_CONFIG_DEFAULTS[AppConfigKey.COIN_PACKS])


class ConfigValidationError(Exception):
    """Raised when an admin-submitted config value is invalid."""


def _is_positive_int(value) -> bool:
    # bool is an int subclass; reject it explicitly.
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _validate_coin_packs(value) -> None:
    if not isinstance(value, list):
        raise ConfigValidationError("coin_packs must be a list.")
    skus: list[str] = []
    for i, pack in enumerate(value):
        if not isinstance(pack, dict):
            raise ConfigValidationError(f"coin_packs[{i}] must be an object.")
        sku = pack.get("sku")
        if not isinstance(sku, str) or not sku:
            raise ConfigValidationError(f"coin_packs[{i}] is missing a valid sku.")
        skus.append(sku)
        if not _is_positive_int(pack.get("coins")):
            raise ConfigValidationError(f"{sku}: coins must be a positive integer.")
        price = pack.get("price_paise")
        original = pack.get("original_price_paise")
        if not _is_positive_int(price):
            raise ConfigValidationError(f"{sku}: price_paise must be a positive integer.")
        if not _is_positive_int(original):
            raise ConfigValidationError(
                f"{sku}: original_price_paise must be a positive integer."
            )
        if original < price:
            raise ConfigValidationError(
                f"{sku}: original_price_paise must be >= price_paise."
            )
    if len(skus) != len(set(skus)):
        raise ConfigValidationError("coin_packs has duplicate skus.")
    if set(skus) != set(_EXPECTED_PACK_SKUS):
        raise ConfigValidationError(
            "coin_packs skus must stay exactly "
            f"{sorted(_EXPECTED_PACK_SKUS)} (no add, remove, or rename)."
        )


def _validate_gesture_pool(value) -> None:
    if not isinstance(value, list) or not value:
        raise ConfigValidationError("gesture_pool must be a non-empty list.")
    codes: list[str] = []
    for i, entry in enumerate(value):
        if not isinstance(entry, dict):
            raise ConfigValidationError(f"gesture_pool[{i}] must be an object.")
        code = entry.get("code")
        if not isinstance(code, str) or not code:
            raise ConfigValidationError(f"gesture_pool[{i}] needs a non-empty code.")
        codes.append(code)
        if not isinstance(entry.get("label"), str) or not entry["label"]:
            raise ConfigValidationError(f"{code}: label must be a non-empty string.")
        if not isinstance(entry.get("emoji"), str) or not entry["emoji"]:
            raise ConfigValidationError(f"{code}: emoji must be a non-empty string.")
    if len(codes) != len(set(codes)):
        raise ConfigValidationError("gesture_pool has duplicate codes.")


def validate_app_config(key: str, value) -> None:
    """Raise ConfigValidationError if an admin-submitted value is invalid.
    Unlisted keys are not constrained here."""
    if key in _POSITIVE_INT_KEYS:
        if not _is_positive_int(value):
            raise ConfigValidationError(f"{key} must be a positive integer.")
    elif key == AppConfigKey.COIN_PACKS:
        _validate_coin_packs(value)
    elif key == AppConfigKey.GESTURE_POOL:
        _validate_gesture_pool(value)
