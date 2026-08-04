"""DEV: force-expire a chat now (test expiry → reveal-on-expiry / extension)."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from ._harness import ensure_dev


class Command(BaseCommand):
    help = "DEV: force-expire a chat immediately."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--chat", required=True, help="Chat id (UUID).")

    def handle(self, *args, **options) -> None:
        ensure_dev()
        from apps.chats.services.chat_service import ChatService

        result = ChatService().expire_chat(options["chat"])
        if result.failed:
            raise CommandError(
                f"expire failed [{result.error_code}]: {result.error_message}"
            )
        self.stdout.write(
            self.style.SUCCESS(f"Chat {options['chat']} -> {result.data.status}")
        )
