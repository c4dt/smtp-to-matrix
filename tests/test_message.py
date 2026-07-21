"""Unit tests for rendering received email into Matrix bodies."""

from email.message import EmailMessage

from smtp_to_matrix.message import render_email

HOST = "testhost"


def _build(**parts: str) -> bytes:
    msg = EmailMessage()
    for header in ("From", "To", "Subject"):
        if header.lower() in parts:
            msg[header] = parts[header.lower()]
    msg.set_content(parts.get("body", ""))
    return msg.as_bytes()


def test_hostname_is_first_line() -> None:
    plain, html_body = render_email(_build(subject="hi", body="x"), HOST)
    assert plain.splitlines()[0] == f"Host: {HOST}"
    assert html_body.startswith(f"<b>Host:</b> {HOST}<br>")


def test_headers_and_body_in_plain() -> None:
    plain, _ = render_email(
        _build(**{"from": "a@x", "to": "b@y", "subject": "hi", "body": "hello world"}),
        HOST,
    )
    assert "From: a@x" in plain
    assert "To: b@y" in plain
    assert "Subject: hi" in plain
    assert "hello world" in plain


def test_html_escapes_content() -> None:
    _, html_body = render_email(
        _build(**{"subject": "<danger>", "body": "1 < 2 & 3"}), HOST
    )
    assert "<b>Subject:</b> &lt;danger&gt;" in html_body
    assert "<pre>1 &lt; 2 &amp; 3</pre>" in html_body


def test_missing_headers_tolerated() -> None:
    plain, html_body = render_email(_build(body="just a body"), HOST)
    assert plain == f"Host: {HOST}\n\njust a body"
    assert "<pre>just a body</pre>" in html_body


def test_multipart_prefers_plain_text() -> None:
    msg = EmailMessage()
    msg["Subject"] = "multi"
    msg.set_content("the plain part")
    msg.add_alternative("<p>the html part</p>", subtype="html")
    plain, _ = render_email(msg.as_bytes(), HOST)
    assert "the plain part" in plain
    assert "the html part" not in plain


def test_html_only_message_falls_back_to_html_body() -> None:
    msg = EmailMessage()
    msg["Subject"] = "htmlonly"
    msg.set_content("<p>only html</p>", subtype="html")
    plain, _ = render_email(msg.as_bytes(), HOST)
    assert "only html" in plain


def test_rfc2047_encoded_subject_decoded() -> None:
    raw = b"Subject: =?utf-8?q?caf=C3=A9?=\n\nbody\n"
    plain, _ = render_email(raw, HOST)
    assert "Subject: café" in plain
