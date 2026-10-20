"""Django admin registration for the reveal app (dev-only operator GUI).

The ``ParticipantDecision`` inline under a ``DecisionRound`` is the primary
surface for hand-editing each user's choice / paid state during local testing.
"""

from __future__ import annotations

from django.contrib import admin

from .models import DecisionRound, ParticipantDecision


class ParticipantDecisionInline(admin.TabularInline):
    model = ParticipantDecision
    extra = 0
    raw_id_fields = ("user",)
    fields = ("user", "choice", "chosen_at", "paid_at", "paid_with_coin")


@admin.register(DecisionRound)
class DecisionRoundAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "chat",
        "trigger",
        "phase",
        "final_call",
        "safe_decision",
        "decision_deadline_at",
        "created_at",
    )
    list_filter = ("phase", "trigger", "final_call", "safe_decision")
    search_fields = ("id", "chat__id")
    raw_id_fields = ("chat",)
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)
    inlines = (ParticipantDecisionInline,)


@admin.register(ParticipantDecision)
class ParticipantDecisionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "round",
        "user",
        "choice",
        "chosen_at",
        "paid_at",
        "paid_with_coin",
    )
    list_filter = ("choice", "paid_with_coin")
    search_fields = ("id", "round__id", "user__id", "user__college_email")
    raw_id_fields = ("round", "user")
