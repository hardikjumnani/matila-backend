"""
Credit / coin wallet service.

Owns ``wallets`` + ``coin_ledger``. Every balance change writes an idempotent
ledger row (unique ``idempotency_key``) under a per-wallet row lock, so retried
credits/consumes never double-apply and concurrent same-user mutations serialize.
See docs/REVEAL_FLOW_SPEC.md.
"""

from __future__ import annotations

import logging

from django.db import transaction

from apps.common.results import ServiceResult
from apps.payments.enums import CoinLedgerReason, CoinType
from apps.payments.models import CoinLedger, Wallet
from apps.users.models import User

logger = logging.getLogger(__name__)

_FIELD_BY_COIN = {
    CoinType.REVEAL: "reveal_coins",
    CoinType.SAFE_REVEAL: "safe_reveal_coins",
}


class CreditService:
    def get_or_create_wallet(self, user: User) -> Wallet:
        return Wallet.objects.get_or_create(user=user)[0]

    def get_balances(self, user: User) -> dict:
        wallet = Wallet.objects.filter(user=user).first()
        return {
            "reveal_coins": wallet.reveal_coins if wallet else 0,
            "safe_reveal_coins": wallet.safe_reveal_coins if wallet else 0,
        }

    def has_coin(self, user: User, coin_type: CoinType | str) -> bool:
        wallet = Wallet.objects.filter(user=user).first()
        if wallet is None:
            return False
        return getattr(wallet, _FIELD_BY_COIN[coin_type]) >= 1

    @transaction.atomic
    def credit(
        self,
        *,
        user: User,
        coin_type: CoinType | str,
        amount: int,
        reason: CoinLedgerReason | str,
        idempotency_key: str,
        chat=None,
        payment=None,
    ) -> ServiceResult[dict]:
        """Add ``amount`` coins, idempotent on ``idempotency_key``."""
        if amount <= 0:
            return ServiceResult.fail("VALIDATION_ERROR", "Credit amount must be > 0.")
        wallet = Wallet.objects.select_for_update().get_or_create(user=user)[0]
        if CoinLedger.objects.filter(idempotency_key=idempotency_key).exists():
            return ServiceResult.ok(self._balances(wallet))  # already applied

        field = _FIELD_BY_COIN[coin_type]
        new_balance = getattr(wallet, field) + amount
        setattr(wallet, field, new_balance)
        wallet.save(update_fields=[field, "updated_at"])
        CoinLedger.objects.create(
            wallet=wallet,
            coin_type=coin_type,
            delta=amount,
            balance_after=new_balance,
            reason=reason,
            chat=chat,
            payment=payment,
            idempotency_key=idempotency_key,
        )
        logger.info(
            "Credited %s x%d to user %s (%s)", coin_type, amount, user.id, reason
        )
        return ServiceResult.ok(self._balances(wallet))

    @transaction.atomic
    def consume(
        self,
        *,
        user: User,
        coin_type: CoinType | str,
        idempotency_key: str,
        chat=None,
    ) -> ServiceResult[dict]:
        """Spend exactly one coin, idempotent on ``idempotency_key``.

        Returns ok with the new balances, or CONFLICT if the balance is zero.
        A repeat call with the same key is a no-op success.
        """
        wallet = Wallet.objects.select_for_update().get_or_create(user=user)[0]
        if CoinLedger.objects.filter(idempotency_key=idempotency_key).exists():
            return ServiceResult.ok(self._balances(wallet))  # already consumed

        field = _FIELD_BY_COIN[coin_type]
        if getattr(wallet, field) < 1:
            return ServiceResult.fail("INSUFFICIENT_COINS", "Insufficient coins.")
        new_balance = getattr(wallet, field) - 1
        setattr(wallet, field, new_balance)
        wallet.save(update_fields=[field, "updated_at"])
        CoinLedger.objects.create(
            wallet=wallet,
            coin_type=coin_type,
            delta=-1,
            balance_after=new_balance,
            reason=CoinLedgerReason.REVEAL_CONSUME,
            chat=chat,
            idempotency_key=idempotency_key,
        )
        return ServiceResult.ok(self._balances(wallet))

    @staticmethod
    def _balances(wallet: Wallet) -> dict:
        return {
            "reveal_coins": wallet.reveal_coins,
            "safe_reveal_coins": wallet.safe_reveal_coins,
        }
