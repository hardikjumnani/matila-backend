"""
Seed runtime configuration (``app_config`` + ``feature_flags``) with
launch-intent values.

Idempotent: every run upserts each key through ``ConfigurationService`` (which
also busts the Redis cache and writes an audit row), so it is safe to re-run.
The system already has code-level fallbacks in ``constants.py``; this command
*persists* the intended launch values to the database so they are auditable and
editable by an admin.

Values a human owns long-term (support email, FAQ, guidelines, versions) start
here as sensible placeholders and are edited afterward via the admin API.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from apps.configuration.constants import (
    APP_CONFIG_DEFAULTS,
    AppConfigKey,
    FeatureFlagKey,
)
from apps.configuration.services.configuration_service import ConfigurationService

# key -> (value, description). Descriptions surface in the admin UI later.
APP_CONFIG_SEED: dict[str, tuple[Any, str]] = {
    AppConfigKey.REVEAL_PRICE_PAISE: (
        3900,
        "Standard reveal price in paise (Rs.39 per side / per coin).",
    ),
    AppConfigKey.SAFE_REVEAL_FEMALE_PRICE_PAISE: (
        6900,
        "Safe reveal price for the girl in paise (Rs.69).",
    ),
    AppConfigKey.SAFE_REVEAL_MALE_PRICE_PAISE: (
        2900,
        "Safe reveal price for the boy in paise (Rs.29).",
    ),
    AppConfigKey.STANDARD_REVEAL_BUNDLES: (
        APP_CONFIG_DEFAULTS[AppConfigKey.STANDARD_REVEAL_BUNDLES],
        "Standard-reveal coin bundles sold in the store (with cut prices).",
    ),
    AppConfigKey.CHAT_EXTENSION_PRICE_PAISE: (
        2900,
        "2-day chat-extension price in paise (Rs.29 per user, repeatable).",
    ),
    AppConfigKey.RATING_QUESTIONNAIRE: (
        APP_CONFIG_DEFAULTS[AppConfigKey.RATING_QUESTIONNAIRE],
        "Post-chat rating questionnaire (v1).",
    ),
    AppConfigKey.GESTURE_POOL: (
        APP_CONFIG_DEFAULTS[AppConfigKey.GESTURE_POOL],
        "Verification gesture pool.",
    ),
    AppConfigKey.MATCHMAKING_TIMEOUT_SECONDS: (
        300,
        "Matchmaking search timeout (seconds).",
    ),
    AppConfigKey.CHAT_EXPIRY_WARNING_MINUTES: (
        60,
        "Minutes before expiry to warn the client.",
    ),
    AppConfigKey.MINIMUM_SUPPORTED_VERSION: ("1.0.0", "Minimum supported client version."),
    AppConfigKey.LATEST_VERSION: ("1.0.0", "Latest available client version."),
    AppConfigKey.SUPPORT_EMAIL: ("support@matila.in", "Support contact email."),
    # Minimal placeholders — the owner fills these in via the admin API later.
    AppConfigKey.FAQ_CONTENT: (
        [
            {
                "q": "What is Matila?",
                "a": "An anonymous, delayed-chat app for verified college students.",
            }
        ],
        "FAQ entries (placeholder — edit via admin).",
    ),
    AppConfigKey.COMMUNITY_GUIDELINES: (
        "Be respectful. No harassment, hate speech, or explicit content. "
        "Report anything that feels off - every report is reviewed.",
        "Community guidelines (placeholder — edit via admin).",
    ),
}

# Launch flag state. Payments + reveal stay OFF until Phase H go-live (prod has
# placeholder Razorpay keys); flipping them on before then exposes broken flows.
FEATURE_FLAG_SEED: dict[str, tuple[bool, str]] = {
    FeatureFlagKey.PAYMENTS_ENABLED: (
        False,
        "Razorpay payments live? OFF until Phase H go-live.",
    ),
    FeatureFlagKey.REVEAL_ENABLED: (
        False,
        "Paid identity reveal enabled? OFF until Phase H (needs live payments).",
    ),
    FeatureFlagKey.IMAGE_MESSAGES_ENABLED: (True, "Image messages in chat."),
    FeatureFlagKey.MAINTENANCE_MODE: (False, "Global maintenance mode."),
}


class Command(BaseCommand):
    help = "Seed app_config and feature_flags with launch-intent values (idempotent)."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be written without touching the database.",
        )

    def handle(self, *args, **options) -> None:
        dry_run: bool = options["dry_run"]
        service = ConfigurationService()

        self.stdout.write(self.style.MIGRATE_HEADING("app_config:"))
        for key, (value, description) in APP_CONFIG_SEED.items():
            if dry_run:
                self.stdout.write(f"  [dry-run] {key} = {value!r}")
            else:
                service.set_config(key=key, value=value, description=description)
                self.stdout.write(self.style.SUCCESS(f"  set {key}"))

        self.stdout.write(self.style.MIGRATE_HEADING("feature_flags:"))
        for key, (value, description) in FEATURE_FLAG_SEED.items():
            if dry_run:
                self.stdout.write(f"  [dry-run] {key} = {value!r}")
            else:
                service.set_flag(key=key, value=value, description=description)
                self.stdout.write(self.style.SUCCESS(f"  set {key} = {value}"))

        summary = "Dry run complete." if dry_run else "Runtime configuration seeded."
        self.stdout.write(self.style.SUCCESS(summary))
