"""Request serializers for the reveal / decision API."""

from __future__ import annotations

from rest_framework import serializers

from apps.reveal.enums import DecisionChoice, SafeRevealDecision


class DecisionRequestSerializer(serializers.Serializer):
    choice = serializers.ChoiceField(choices=DecisionChoice.choices)


class SafeDecisionRequestSerializer(serializers.Serializer):
    choice = serializers.ChoiceField(
        choices=[
            (SafeRevealDecision.REVEAL_YOURSELF, "Reveal yourself"),
            (SafeRevealDecision.EXIT, "Exit"),
        ]
    )
