"""Backfill ``User.has_completed_reveal`` for users who already completed a full
reveal before the first-reveal discount shipped, so veterans are not granted a
fresh discount. A completed full reveal = a ParticipantDecision with choice REVEAL
in a round whose final_call is REVEAL and which resolved. See
docs/FIRST_REVEAL_DISCOUNT_PLAN.md."""

from __future__ import annotations

from django.db import migrations


def backfill(apps, schema_editor):
    User = apps.get_model("users", "User")
    ParticipantDecision = apps.get_model("reveal", "ParticipantDecision")
    uids = (
        ParticipantDecision.objects.filter(
            choice="REVEAL",
            round__final_call="REVEAL",
            round__phase="RESOLVED",
        )
        .values_list("user_id", flat=True)
        .distinct()
    )
    User.objects.filter(id__in=list(uids), has_completed_reveal=False).update(
        has_completed_reveal=True
    )


def noop_reverse(apps, schema_editor):
    # Non-reversible data backfill; leave flags as-is on reverse.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0007_has_completed_reveal"),
        ("reveal", "0002_decisionround_participantdecision_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill, noop_reverse),
    ]
