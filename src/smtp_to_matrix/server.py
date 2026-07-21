"""SMTP server that forwards every received message to a Matrix room.

Mail is accepted regardless of recipient and posted to the room named by
``MATRIX_ROOM_ID``. Matrix credentials and the room are resolved once at
startup; each delivery reuses the cached token and room id.
"""

from __future__ import annotations

import asyncio
import os
import socket
import sys
import threading

import httpx
from aiosmtpd.controller import Controller

from smtp_to_matrix import matrix
from smtp_to_matrix.message import render_email

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 25


def _log(message: str) -> None:
    """Write a prefixed line to stderr."""
    print(f"smtp-to-matrix: {message}", file=sys.stderr)


class MatrixHandler:
    """aiosmtpd handler that posts each received message to a Matrix room."""

    def __init__(
        self, homeserver: str, token: str, room_id: str, hostname: str
    ) -> None:
        self.homeserver = homeserver
        self.token = token
        self.room_id = room_id
        self.hostname = hostname

    def _deliver(self, plain: str, html_body: str) -> str:
        """Post the rendered message to Matrix (blocking); returns event id."""
        return matrix.send_html(
            self.homeserver, self.token, self.room_id, plain, html_body
        )

    async def handle_DATA(self, server, session, envelope) -> str:  # noqa: N802
        """Render the message and forward it to Matrix off the event loop."""
        plain, html_body = render_email(envelope.content, self.hostname)
        try:
            event_id = await asyncio.to_thread(self._deliver, plain, html_body)
        except httpx.HTTPError as exc:
            _log(f"delivery failed: {exc}")
            return "451 Requested action aborted: Matrix delivery failed"
        _log(f"delivered to {self.room_id} as {event_id}")
        return "250 Message accepted for delivery"


def main() -> int:
    """Resolve Matrix config, then run the SMTP server until interrupted."""
    homeserver = os.environ.get("MATRIX_HOMESERVER_URL")
    room = os.environ.get("MATRIX_ROOM_ID")
    if not homeserver or not room:
        _log("set MATRIX_HOMESERVER_URL and MATRIX_ROOM_ID")
        return 78  # EX_CONFIG

    host = os.environ.get("SMTP_HOST", DEFAULT_HOST)
    port = int(os.environ.get("SMTP_PORT", DEFAULT_PORT))
    host_label = os.environ.get("MATRIX_HOST_LABEL") or socket.gethostname()

    try:
        token = matrix.resolve_token(homeserver)
        room_id = matrix.resolve_room(homeserver, token, room)
    except (RuntimeError, httpx.HTTPError) as exc:
        _log(f"configuration error: {exc}")
        return 78  # EX_CONFIG

    handler = MatrixHandler(homeserver, token, room_id, host_label)
    controller = Controller(handler, hostname=host, port=port)
    controller.start()
    _log(f"listening on {host}:{port}, forwarding to {room_id}")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        _log("shutting down")
    finally:
        controller.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
