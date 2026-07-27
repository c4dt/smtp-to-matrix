"""Render a received RFC-822 email into Matrix plain-text and HTML bodies."""

from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import datetime
from email import message_from_bytes
from email.message import EmailMessage
from email.policy import default
from email.utils import parsedate_to_datetime

from bs4 import BeautifulSoup

_HEADERS = ("From", "To", "Subject")


@dataclass(frozen=True)
class MailMeta:
    """Fields extracted from a received mail for matching and summarising."""

    host: str
    sender: str
    subject: str
    body: str
    date: datetime


def _text_body(msg: EmailMessage) -> str:
    """Return the message's text body, preferring plain text over HTML."""
    body = msg.get_body(preferencelist=("plain", "html"))
    if body is None:
        return ""
    content = body.get_content()
    return content if isinstance(content, str) else content.decode(errors="replace")


def _is_html_email(msg: EmailMessage) -> bool:
    """Return true if the email is in HTML format, else false"""
    return any(part.get_content_type() == "text/html" for part in msg.walk())


def render_email(raw: bytes, hostname: str) -> tuple[str, str]:
    """Parse raw email bytes into ``(plain_body, html_body)`` for Matrix.

    The first line is ``Host: {hostname}`` (the server that received the mail),
    followed by the mail's ``Date`` and a small ``From``/``To``/``Subject``
    header block and the message's text body. Missing headers and bodies are
    tolerated; the ``Date`` falls back to receive-time when absent.
    """
    msg = message_from_bytes(raw, policy=default)
    when = _mail_date(msg).astimezone().strftime("%Y-%m-%d %H:%M")
    headers = [("Host", hostname), ("Date", when)]
    headers += [(name, msg[name]) for name in _HEADERS if msg[name]]
    body = _text_body(msg).strip()
    # convert body from HTML to readable format
    if _is_html_email(msg):
        heading_map = {"h1": "# ", "h2": "## ", "h3": "### ", "h4": "#### "}
        soup = BeautifulSoup(body, features="html.parser")
        for tag_name, prefix in heading_map.items():
            for tag in soup.find_all(tag_name):
                tag.string = f"{prefix}{tag.get_text(strip=True)}"
        formatted_body: str = soup.get_text(separator="\n", strip=True)
    else:
        formatted_body: str = body

    plain_lines = [f"{name}: {value}" for name, value in headers]
    plain_lines.append("")
    plain_lines.append(body)
    plain = "\n".join(plain_lines).strip()

    html_headers = "".join(
        f"<b>{html.escape(name)}:</b> {html.escape(str(value))}<br>\n"
        for name, value in headers
    )
    html_body = f"{html_headers}<pre>{html.escape(formatted_body)}</pre>"

    return plain, html_body


def _mail_date(msg: EmailMessage) -> datetime:
    """Return the message ``Date`` (local-aware); fall back to now if missing."""
    try:
        date = parsedate_to_datetime(msg["Date"]) if msg["Date"] else None
    except (ValueError, TypeError):
        date = None
    return date or datetime.now().astimezone()


def parse_meta(raw: bytes, host: str) -> MailMeta:
    """Extract the fields used for rule matching, storage and summaries."""
    msg = message_from_bytes(raw, policy=default)
    return MailMeta(
        host=host,
        sender=str(msg["From"]) if msg["From"] else "",
        subject=str(msg["Subject"]) if msg["Subject"] else "",
        body=_text_body(msg).strip(),
        date=_mail_date(msg),
    )


def summary_line(meta: MailMeta) -> str:
    """Build the one-line summary: ``date - sender@host - subject``."""
    when = meta.date.astimezone().strftime("%Y-%m-%d %H:%M")
    return f"{when} - {meta.sender}@{meta.host} - {meta.subject}"
