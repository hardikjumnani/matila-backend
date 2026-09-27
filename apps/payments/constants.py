"""Payments domain constants.

See docs/REVEAL_FLOW_SPEC.md. Google Play managed-product (consumable) IDs are
mapped to the purpose they unlock. Prices live in the Play Console and must match
the runtime config; the backend trusts the (verified) product_id -> purpose
mapping and resolves the ledger amount from config.

``reveal_unlock`` is retired: standard reveals are now funded by ``reveal_coins``
bought via the ``standard_reveal_*`` bundles (CREDIT_PURCHASE) or credited on a
cancelled payment.
"""

from __future__ import annotations

from apps.payments.enums import PaymentPurpose

PLAY_PRODUCT_TO_PURPOSE: dict[str, str] = {
    # Store bundles → grant reveal_coins.
    "standard_reveal_1": PaymentPurpose.CREDIT_PURCHASE,
    "standard_reveal_3": PaymentPurpose.CREDIT_PURCHASE,
    "standard_reveal_5": PaymentPurpose.CREDIT_PURCHASE,
    "standard_reveal_10": PaymentPurpose.CREDIT_PURCHASE,
    # Safe reveal — role-priced SKUs, both map to the SAFE_REVEAL purpose.
    "safe_reveal_female": PaymentPurpose.SAFE_REVEAL,
    "safe_reveal_male": PaymentPurpose.SAFE_REVEAL,
    # Chat extension (real money, per 2-day cycle).
    "chat_extension": PaymentPurpose.CHAT_EXTENSION,
}

# Safe-reveal SKU expected for each payer gender (server validates the client's
# product_id against the payer's gender so no one is mischarged).
SAFE_REVEAL_SKU_BY_GENDER: dict[str, str] = {
    "MALE": "safe_reveal_male",
    "FEMALE": "safe_reveal_female",
}
