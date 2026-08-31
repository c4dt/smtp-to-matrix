"""SMTP server that forwards every received message to a Matrix room.

Mail is accepted regardless of recipient and posted to the room named by
``MATRIX_ROOM_ID``. Matrix credentials and the room are resolved once at
startup; each delivery reuses the cached token and room id.
"""

from __future__ import annotations

import asyncio
import html
import os
import socket
import sys
import threading

import httpx
from aiosmtpd.controller import Controller

from smtp_to_matrix import config, matrix, scheduler
from smtp_to_matrix.config import Config, Severity
from smtp_to_matrix.message import MailMeta, parse_meta, render_email, summary_line
from smtp_to_matrix.store import Store

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 25
DEFAULT_DB_PATH = "pending_mail.db"


def _log(message: str) -> None:
    """Write a prefixed line to stderr."""
    print(f"smtp-to-matrix: {message}", file=sys.stderr)


class MatrixHandler:
    """aiosmtpd handler that posts each received message to a Matrix room."""

    def __init__(
        self,
        homeserver: str,
        token: str,
        room_id: str,
        hostname: str,
        config: Config,
        store: Store,
    ) -> None:
        self.homeserver = homeserver
        self.token = token
        self.room_id = room_id
        self.hostname = hostname
        self.config = config
        self.store = store

    def _send_now(self, summary: str, messages: list[tuple[str, str]]) -> str:
        """Post the summary root, then each message chunk as a threaded reply."""
        root = matrix.send_html(
            self.homeserver, self.token, self.room_id, summary, html.escape(summary)
        )
        for plain, html_body in messages:
            matrix.send_html(
                self.homeserver,
                self.token,
                self.room_id,
                plain,
                html_body,
                thread_root=root,
            )
        return root

    def _resolve_severity(self, meta: MailMeta, exception: bool) -> Severity | None:
        """Determine the severity level for a send-now message."""
        if exception and self.config.exception_severity is not None:
            return self.config.exception_severity
        return (
            config.classify_severity(self.config, meta) or self.config.default_severity
        )

    async def handle_DATA(self, server, session, envelope) -> str:  # noqa: N802
        """Classify the message; send it now or hold it for its batch digest."""
        meta = parse_meta(envelope.content, self.hostname)
        result = config.classify(self.config, meta)
        if result.batch is not None:
            self.store.add(result.batch, envelope.content, meta)
            _log(f"held in batch {result.batch!r}: {meta.subject!r}")
            return "250 Message accepted for delivery"

        messages = render_email(envelope.content, self.hostname)
        summary = summary_line(meta)
        severity = self._resolve_severity(meta, result.exception)
        if severity is not None:
            summary = f"{severity.emoji} {summary}"
        try:
            root = await asyncio.to_thread(self._send_now, summary, messages)
        except httpx.HTTPError as exc:
            _log(f"delivery failed: {exc}")
            return "451 Requested action aborted: Matrix delivery failed"
        _log(f"delivered to {self.room_id} as {root}")
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
        cfg = config.load(os.environ.get("CONFIG_PATH"))
    except (RuntimeError, httpx.HTTPError) as exc:
        _log(f"configuration error: {exc}")
        return 78  # EX_CONFIG

    store = Store(os.environ.get("DB_PATH", DEFAULT_DB_PATH))
    store.init()

    handler = MatrixHandler(homeserver, token, room_id, host_label, cfg, store)
    controller = Controller(handler, hostname=host, port=port)
    controller.start()
    _log(f"listening on {host}:{port}, forwarding to {room_id}")
    try:
        if cfg.batches:
            asyncio.run(scheduler.run(homeserver, token, room_id, store, cfg))
        else:
            threading.Event().wait()
    except KeyboardInterrupt:
        _log("shutting down")
    finally:
        controller.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
