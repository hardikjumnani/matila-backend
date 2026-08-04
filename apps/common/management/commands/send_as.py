"""DEV: send a message into a chat AS a given user (drive the seeded partner)."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from ._harness import ensure_dev, get_user


class Command(BaseCommand):
    help = "DEV: send a text message into a chat as a given user."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--as", dest="as_email", required=True, help="Sender's college email."
        )
        parser.add_argument("--chat", required=True, help="Chat id (UUID).")
        parser.add_argument("--text", required=True, help="Message body.")

    def handle(self, *args, **options) -> None:
        ensure_dev()
        sender = get_user(options["as_email"])
        from apps.messaging.services.message_service import MessageService

        result = MessageService().send_text(
            chat_id=options["chat"], sender=sender, content=options["text"]
        )
        if result.failed:
            raise CommandError(
                f"send failed [{result.error_code}]: {result.error_message}"
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"Sent as {sender.college_email}: message {result.data.id}"
            )
        )
