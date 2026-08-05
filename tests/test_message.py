"""Unit tests for rendering received email into Matrix bodies."""

import re
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import parsedate_to_datetime

from smtp_to_matrix.message import parse_meta, render_email, summary_line

HOST = "testhost"
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}")


def _build(**parts: str) -> bytes:
    msg = EmailMessage()
    for header in ("From", "To", "Subject", "Date"):
        if header.lower() in parts:
            msg[header] = parts[header.lower()]
    msg.set_content(parts.get("body", ""))
    return msg.as_bytes()


def test_hostname_is_first_line() -> None:
    msgs = render_email(_build(subject="hi", body="x"), HOST)
    plain, html_body = msgs[0]
    assert plain.splitlines()[0] == f"Host: {HOST}"
    assert html_body.startswith(f"<b>Host:</b> {HOST}<br>")


def test_headers_and_body_in_plain() -> None:
    msgs = render_email(
        _build(**{"from": "a@x", "to": "b@y", "subject": "hi", "body": "hello world"}),
        HOST,
    )
    plain, _ = msgs[0]
    assert "From: a@x" in plain
    assert "To: b@y" in plain
    assert "Subject: hi" in plain
    assert "hello world" in plain


def test_html_escapes_content() -> None:
    msgs = render_email(_build(**{"subject": "<danger>", "body": "1 < 2 & 3"}), HOST)
    _, html_body = msgs[0]
    assert "<b>Subject:</b> &lt;danger&gt;" in html_body
    assert "<pre>1 &lt; 2 &amp; 3</pre>" in html_body


def test_missing_headers_tolerated() -> None:
    msgs = render_email(_build(body="just a body"), HOST)
    plain, html_body = msgs[0]
    lines = plain.splitlines()
    assert lines[0] == f"Host: {HOST}"
    assert lines[1].startswith("Date: ")
    assert _DATE_RE.fullmatch(lines[1].removeprefix("Date: "))
    assert "just a body" in plain
    assert "<pre>just a body</pre>" in html_body


def test_date_is_second_line() -> None:
    raw = _build(subject="hi", date="Mon, 02 Jan 2023 03:04:05 +0000", body="x")
    msgs = render_email(raw, HOST)
    plain, _ = msgs[0]
    lines = plain.splitlines()
    assert lines[0] == f"Host: {HOST}"
    assert lines[1].startswith("Date: ")


def test_date_matches_mail_header() -> None:
    raw = _build(subject="hi", date="Mon, 02 Jan 2023 03:04:05 +0000", body="x")
    msgs = render_email(raw, HOST)
    plain, _ = msgs[0]
    expected = (
        parsedate_to_datetime("Mon, 02 Jan 2023 03:04:05 +0000")
        .astimezone()
        .strftime("%Y-%m-%d %H:%M")
    )
    assert f"Date: {expected}" in plain


def test_missing_date_header_still_renders_date_line() -> None:
    msgs = render_email(_build(subject="hi", body="x"), HOST)
    plain, _ = msgs[0]
    line = plain.splitlines()[1]
    assert line.startswith("Date: ")
    assert _DATE_RE.fullmatch(line.removeprefix("Date: "))


def test_multipart_prefers_plain_text() -> None:
    msg = EmailMessage()
    msg["Subject"] = "multi"
    msg.set_content("the plain part")
    msg.add_alternative("<p>the html part</p>", subtype="html")
    msgs = render_email(msg.as_bytes(), HOST)
    plain, _ = msgs[0]
    assert "the plain part" in plain
    assert "the html part" not in plain


def test_html_only_message_falls_back_to_html_body() -> None:
    msg = EmailMessage()
    msg["Subject"] = "htmlonly"
    msg.set_content("<p>only html</p>", subtype="html")
    msgs = render_email(msg.as_bytes(), HOST)
    plain, _ = msgs[0]
    assert "only html" in plain


def test_rfc2047_encoded_subject_decoded() -> None:
    raw = b"Subject: =?utf-8?q?caf=C3=A9?=\n\nbody\n"
    msgs = render_email(raw, HOST)
    plain, _ = msgs[0]
    assert "Subject: café" in plain


def test_parse_meta_extracts_fields() -> None:
    raw = _build(**{"from": "a@x", "to": "b@y", "subject": "hi", "body": "hello"})
    meta = parse_meta(raw, HOST)
    assert meta.host == HOST
    assert meta.sender == "a@x"
    assert meta.subject == "hi"
    assert "hello" in meta.body


def test_parse_meta_missing_headers_are_empty() -> None:
    meta = parse_meta(_build(body="x"), HOST)
    assert meta.sender == ""
    assert meta.subject == ""


def test_parse_meta_uses_date_header() -> None:
    raw = b"Subject: hi\nDate: Mon, 02 Jan 2023 03:04:05 +0000\n\nbody\n"
    meta = parse_meta(raw, HOST)
    assert meta.date == datetime(2023, 1, 2, 3, 4, 5, tzinfo=UTC)


def test_parse_meta_falls_back_to_now_without_date() -> None:
    before = datetime.now().astimezone()
    meta = parse_meta(_build(subject="hi", body="x"), HOST)
    assert meta.date >= before


def test_summary_line_format() -> None:
    raw = (
        b"Subject: disk full\nFrom: ops@localhost\n"
        b"Date: Mon, 02 Jan 2023 03:04:05 +0000\n\nbody\n"
    )
    meta = parse_meta(raw, HOST)
    expected_time = meta.date.astimezone().strftime("%Y-%m-%d %H:%M")
    assert summary_line(meta) == (f"{expected_time} - ops@localhost@{HOST} - disk full")
