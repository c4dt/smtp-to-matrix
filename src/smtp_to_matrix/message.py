"""Render a received RFC-822 email into Matrix plain-text and HTML bodies."""

from __future__ import annotations

import html
from email import message_from_bytes
from email.message import EmailMessage
from email.policy import default

_HEADERS = ("From", "To", "Subject")


def _text_body(msg: EmailMessage) -> str:
    """Return the message's text body, preferring plain text over HTML."""
    body = msg.get_body(preferencelist=("plain", "html"))
    if body is None:
        return ""
    content = body.get_content()
    return content if isinstance(content, str) else content.decode(errors="replace")


def render_email(raw: bytes, hostname: str) -> tuple[str, str]:
    """Parse raw email bytes into ``(plain_body, html_body)`` for Matrix.

    The first line is ``Host: {hostname}`` (the server that received the mail),
    followed by a small ``From``/``To``/``Subject`` header block and the
    message's text body. Missing headers and bodies are tolerated.
    """
    msg = message_from_bytes(raw, policy=default)
    headers = [("Host", hostname)]
    headers += [(name, msg[name]) for name in _HEADERS if msg[name]]
    body = _text_body(msg).strip()

    plain_lines = [f"{name}: {value}" for name, value in headers]
    plain_lines.append("")
    plain_lines.append(body)
    plain = "\n".join(plain_lines).strip()

    html_headers = "".join(
        f"<b>{html.escape(name)}:</b> {html.escape(str(value))}<br>\n"
        for name, value in headers
    )
    html_body = f"{html_headers}<pre>{html.escape(body)}</pre>"

    return plain, html_body
