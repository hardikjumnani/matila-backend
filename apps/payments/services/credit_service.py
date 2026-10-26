"""
Credit / coin wallet service.

Owns ``wallets`` + ``coin_ledger``. One unified Coin balance. Every balance change
writes an idempotent ledger row (unique ``idempotency_key``) under a per-wallet row
lock, so retried credits/spends never double-apply and concurrent same-user mutations
serialize. See docs/COIN_REWORK_PLAN.md.
"""

from __future__ import annotations

import logging

from django.db import transaction

from apps.common.results import ServiceResult
from apps.payments.enums import CoinLedgerReason, CoinType
from apps.payments.models import CoinLedger, Wallet
from apps.users.models import User

logger = logging.getLogger(__name__)


class CreditService:
    def get_or_create_wallet(self, user: User) -> Wallet:
        return Wallet.objects.get_or_create(user=user)[0]

    def get_balances(self, user: User) -> dict:
        wallet = Wallet.objects.filter(user=user).first()
        return {
            "coins": wallet.coins if wallet else 0,
            "has_held_coins": bool(wallet and wallet.has_held_coins),
        }

    def has_coins(self, user: User, amount: int) -> bool:
        wallet = Wallet.objects.filter(user=user).first()
        return bool(wallet and wallet.coins >= amount)

    @transaction.atomic
    def credit(
        self,
        *,
        user: User,
        amount: int,
        reason: CoinLedgerReason | str,
        idempotency_key: str,
        chat=None,
        payment=None,
        purpose: str = "",
        note: str = "",
    ) -> ServiceResult[dict]:
        """Add ``amount`` coins, idempotent on ``idempotency_key``."""
        if amount <= 0:
            return ServiceResult.fail("VALIDATION_ERROR", "Credit amount must be > 0.")
        wallet = Wallet.objects.select_for_update().get_or_create(user=user)[0]
        if CoinLedger.objects.filter(idempotency_key=idempotency_key).exists():
            return ServiceResult.ok(self._balances(wallet))  # already applied

        wallet.coins += amount
        wallet.has_held_coins = True  # sticky: set on the first ever credit
        wallet.save(update_fields=["coins", "has_held_coins", "updated_at"])
        CoinLedger.objects.create(
            wallet=wallet,
            coin_type=CoinType.COIN,
            delta=amount,
            balance_after=wallet.coins,
            reason=reason,
            chat=chat,
            payment=payment,
            purpose=str(purpose or ""),
            note=note or "",
            idempotency_key=idempotency_key,
        )
        logger.info("Credited %d coins to user %s (%s)", amount, user.id, reason)
        return ServiceResult.ok(self._balances(wallet))

    @transaction.atomic
    def spend(
        self,
        *,
        user: User,
        amount: int,
        idempotency_key: str,
        reason: CoinLedgerReason | str = CoinLedgerReason.ACTION_CONSUME,
        chat=None,
        purpose: str = "",
    ) -> ServiceResult[dict]:
        """Spend ``amount`` coins, idempotent on ``idempotency_key``.

        Returns ok with the new balances, INSUFFICIENT_COINS if the balance is too
        low, or VALIDATION_ERROR if amount <= 0. A repeat call with the same key is a
        no-op success.
        """
        if amount <= 0:
            return ServiceResult.fail("VALIDATION_ERROR", "Spend amount must be > 0.")
        wallet = Wallet.objects.select_for_update().get_or_create(user=user)[0]
        if CoinLedger.objects.filter(idempotency_key=idempotency_key).exists():
            return ServiceResult.ok(self._balances(wallet))  # already spent

        if wallet.coins < amount:
            return ServiceResult.fail("INSUFFICIENT_COINS", "Insufficient coins.")
        wallet.coins -= amount
        wallet.save(update_fields=["coins", "updated_at"])
        CoinLedger.objects.create(
            wallet=wallet,
            coin_type=CoinType.COIN,
            delta=-amount,
            balance_after=wallet.coins,
            reason=reason,
            chat=chat,
            purpose=str(purpose or ""),
            idempotency_key=idempotency_key,
        )
        return ServiceResult.ok(self._balances(wallet))

    # -- Admin read helpers (per-user coin ledger tab) ----------------------
    def get_ledger_queryset(self, user: User):
        """Full coin history for a user, newest first (admin coin ledger tab)."""
        return (
            CoinLedger.objects.filter(wallet__user=user)
            .select_related("payment", "chat")
            .order_by("-created_at")
        )

    def get_coin_overview(self, user: User) -> dict:
        """Balance + lifetime totals for the admin coin tab. A never-transacted user
        returns a zeroed overview (everyone starts at zero coins)."""
        from django.db.models import Sum

        from apps.payments.enums import CoinLedgerReason, PaymentPurpose, PaymentStatus
        from apps.payments.models import Payment

        wallet = Wallet.objects.filter(user=user).first()
        ledger = CoinLedger.objects.filter(wallet__user=user)

        def _sum(qs) -> int:
            return qs.aggregate(s=Sum("delta"))["s"] or 0

        rupees = (
            Payment.objects.filter(
                user=user,
                purpose=PaymentPurpose.CREDIT_PURCHASE,
                status=PaymentStatus.SUCCESS,
            ).aggregate(s=Sum("amount_in_paise"))["s"]
            or 0
        )
        return {
            "coins": wallet.coins if wallet else 0,
            "has_held_coins": bool(wallet and wallet.has_held_coins),
            "wallet_updated_at": wallet.updated_at if wallet else None,
            "totals": {
                "purchased_coins": _sum(
                    ledger.filter(reason=CoinLedgerReason.BUNDLE_PURCHASE)
                ),
                "refunded_coins": _sum(
                    ledger.filter(reason=CoinLedgerReason.CANCELLATION_CREDIT)
                ),
                "admin_adjusted_coins": _sum(
                    ledger.filter(reason=CoinLedgerReason.ADMIN_ADJUST)
                ),
                "spent_coins": abs(_sum(ledger.filter(delta__lt=0))),
                "lifetime_rupees_paise": rupees,
            },
        }

    @staticmethod
    def _balances(wallet: Wallet) -> dict:
        return {"coins": wallet.coins, "has_held_coins": wallet.has_held_coins}
