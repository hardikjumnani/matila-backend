"""Payments domain constants."""

from __future__ import annotations

from apps.payments.enums import PaymentPurpose

# Google Play managed-product (consumable) IDs mapped to the purpose they unlock.
# The product's price is set in the Play Console and must match the runtime
# ``reveal_price_paise`` / ``chat_extension_price_paise`` config (Rs.39 / Rs.29).
# ``chat_extension`` is consumed once per 2-day extension cycle and is repeatable.
# The backend trusts the (verified) product_id -> purpose mapping; the actual
# charge is Play's, so the amount is resolved from config for the ledger.
PLAY_PRODUCT_TO_PURPOSE: dict[str, str] = {
    "reveal_unlock": PaymentPurpose.REVEAL,
    "chat_extension": PaymentPurpose.CHAT_EXTENSION,
}
