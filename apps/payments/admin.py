"""Django admin registration for the payments app (dev-only operator GUI).

NOTE: ``Wallet.coins`` is editable here for convenience, but balance changes in
the app normally go through ``CreditService`` (which writes an idempotent
``CoinLedger`` row). A bare edit here bypasses that ledger, so use it only for
local testing.
"""

from __future__ import annotations

from django.contrib import admin

from .models import CoinLedger, Payment, Wallet


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "chat",
        "purpose",
        "amount_in_paise",
        "status",
        "provider",
        "initiated_from",
        "created_at",
    )
    list_filter = ("purpose", "status", "provider", "initiated_from")
    search_fields = (
        "id",
        "user__id",
        "chat__id",
        "provider_order_id",
        "provider_payment_id",
    )
    raw_id_fields = ("user", "chat")
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)


class CoinLedgerInline(admin.TabularInline):
    model = CoinLedger
    extra = 0
    raw_id_fields = ("chat", "payment")
    fields = ("coin_type", "delta", "balance_after", "reason", "idempotency_key", "created_at")
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "coins", "has_held_coins", "updated_at")
    list_filter = ("has_held_coins",)
    search_fields = ("id", "user__id", "user__college_email")
    raw_id_fields = ("user",)
    inlines = (CoinLedgerInline,)


@admin.register(CoinLedger)
class CoinLedgerAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "wallet",
        "coin_type",
        "delta",
        "balance_after",
        "reason",
        "idempotency_key",
        "created_at",
    )
    list_filter = ("coin_type", "reason")
    search_fields = ("id", "wallet__id", "idempotency_key")
    raw_id_fields = ("wallet", "chat", "payment")
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)
