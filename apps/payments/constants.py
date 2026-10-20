"""Payments domain constants.

See docs/COIN_REWORK_PLAN.md. Google Play managed-product (consumable) IDs are
mapped to the purpose they unlock. Prices live in the Play Console and must match
the runtime config; the backend trusts the (verified) product_id -> purpose
mapping and resolves the ledger amount from config.

Two tiers: a user either spends unified coins on an action, or buys the action
directly at its cash price via its direct SKU. Coins are bought via the
``coin_pack_*`` store SKUs (CREDIT_PURCHASE).
"""

from __future__ import annotations

from apps.payments.enums import PaymentPurpose

PLAY_PRODUCT_TO_PURPOSE: dict[str, str] = {
    # Store coin packs → grant unified coins.
    "coin_pack_10": PaymentPurpose.CREDIT_PURCHASE,
    "coin_pack_30": PaymentPurpose.CREDIT_PURCHASE,
    "coin_pack_50": PaymentPurpose.CREDIT_PURCHASE,
    "coin_pack_100": PaymentPurpose.CREDIT_PURCHASE,
    # Direct-cash per-action SKUs.
    "reveal": PaymentPurpose.REVEAL,
    "safe_reveal_female": PaymentPurpose.SAFE_REVEAL,
    "safe_reveal_male": PaymentPurpose.SAFE_REVEAL,
    "chat_extension": PaymentPurpose.CHAT_EXTENSION,
}

# Safe-reveal SKU expected for each payer gender (server validates the client's
# product_id against the payer's gender so no one is mischarged).
SAFE_REVEAL_SKU_BY_GENDER: dict[str, str] = {
    "MALE": "safe_reveal_male",
    "FEMALE": "safe_reveal_female",
}
