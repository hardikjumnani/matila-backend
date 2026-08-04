"""DEV: send an image message into a chat as a given user (drive the partner)."""

from __future__ import annotations

import io
import random
import struct
import uuid
import zlib

from django.core.management.base import BaseCommand, CommandError

from apps.messaging.enums import MediaVisibility

from ._harness import ensure_dev, get_user

_PALETTE = [
    (0x2E, 0x86, 0xAB),  # blue
    (0xA2, 0x3B, 0x72),  # magenta
    (0xF1, 0x8F, 0x01),  # amber
    (0x3B, 0x8C, 0x5A),  # green
    (0xC0, 0x39, 0x2B),  # red
]


def _solid_png(size: int, rgb: tuple[int, int, int]) -> bytes:
    """Build a solid-color RGB PNG with the stdlib (no Pillow dependency)."""

    def chunk(ctype: bytes, data: bytes) -> bytes:
        body = ctype + data
        return (
            struct.pack(">I", len(data))
            + body
            + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)  # 8-bit RGB
    row = b"\x00" + bytes(rgb) * size  # filter byte + pixels
    raw = row * size
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


class Command(BaseCommand):
    help = "DEV: send an image message into a chat as a given user."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--as", dest="as_email", required=True, help="Sender's college email."
        )
        parser.add_argument("--chat", required=True, help="Chat id (UUID).")
        parser.add_argument(
            "--file",
            default=None,
            help="Path to an image; if omitted, a generated solid-color PNG is used.",
        )
        parser.add_argument("--size", type=int, default=240)
        parser.add_argument(
            "--view-once",
            action="store_true",
            help="Send as VIEW_ONCE (consumed after one view).",
        )

    def handle(self, *args, **options) -> None:
        ensure_dev()
        sender = get_user(options["as_email"])

        if options["file"]:
            with open(options["file"], "rb") as handle:
                data = handle.read()
            name = options["file"].replace("\\", "/").split("/")[-1]
            content_type = (
                "image/jpeg"
                if name.lower().endswith((".jpg", ".jpeg"))
                else "image/png"
            )
        else:
            data = _solid_png(options["size"], random.choice(_PALETTE))
            name = f"harness_{uuid.uuid4().hex[:8]}.png"
            content_type = "image/png"

        from apps.messaging.services.message_service import MessageService

        visibility = (
            MediaVisibility.VIEW_ONCE
            if options["view_once"]
            else MediaVisibility.NORMAL
        )
        result = MessageService().send_image(
            chat_id=options["chat"],
            sender=sender,
            fileobj=io.BytesIO(data),
            filename=name,
            content_type=content_type,
            visibility=visibility,
        )
        if result.failed:
            raise CommandError(
                f"send_image failed [{result.error_code}]: {result.error_message}"
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"Sent image as {sender.college_email}: message {result.data.id} "
                f"visibility={visibility}"
            )
        )
