"""Tests for the Matrix client helper."""

import json

import httpx
import respx

from smtp_to_matrix import matrix
from smtp_to_matrix.message import render_email

HOMESERVER = "https://matrix.test"
ROOM_ID = "!room:test"
TOKEN = "tok_test"


@respx.mock
def test_identical_messages_use_distinct_transaction_ids() -> None:
    """Regression: duplicate mails must not dedupe on the Matrix server."""
    route = respx.route(method="PUT", url__regex=r".*/send/m\.room\.message/.*").mock(
        return_value=httpx.Response(200, json={"event_id": "$evt"})
    )

    for _ in range(2):
        matrix.send_html(HOMESERVER, TOKEN, ROOM_ID, "body", "<pre>body</pre>")

    assert route.call_count == 2
    first, second = (str(call.request.url) for call in route.calls)
    assert first != second


@respx.mock
def test_thread_root_adds_thread_relation() -> None:
    route = respx.route(method="PUT", url__regex=r".*/send/m\.room\.message/.*").mock(
        return_value=httpx.Response(200, json={"event_id": "$evt"})
    )

    matrix.send_html(
        HOMESERVER, TOKEN, ROOM_ID, "body", "<pre>body</pre>", thread_root="$root"
    )

    body = json.loads(route.calls.last.request.content)
    relation = body["m.relates_to"]
    assert relation["rel_type"] == "m.thread"
    assert relation["event_id"] == "$root"
    assert relation["m.in_reply_to"] == {"event_id": "$root"}


@respx.mock
def test_no_thread_relation_without_root() -> None:
    route = respx.route(method="PUT", url__regex=r".*/send/m\.room\.message/.*").mock(
        return_value=httpx.Response(200, json={"event_id": "$evt"})
    )

    matrix.send_html(HOMESERVER, TOKEN, ROOM_ID, "body", "<pre>body</pre>")

    body = json.loads(route.calls.last.request.content)
    assert "m.relates_to" not in body


@respx.mock
def test_large_message_is_sent_in_parts() -> None:
    """Large messages should be split into multiple Matrix events."""
    route = respx.route(method="PUT", url__regex=r".*/send/m\.room\.message/.*").mock(
        return_value=httpx.Response(200, json={"event_id": "$evt"})
    )
    # Build a large raw message and let render_email split it into parts. The
    # client code would post a summary root first, then each chunk threaded
    # underneath — so the first PUT has no thread relation, subsequent ones do.
    large = "A" * 70000
    raw = f"Subject: big\n\n{large}\n".encode()

    parts = render_email(raw, "senderhost")
    assert len(parts) >= 2
    # Header block should appear only in the first chunk's HTML
    assert "<b>Host:</b>" in parts[0][1]
    assert "<b>Host:</b>" not in parts[1][1]

    # Simulate sending: root summary first
    root = matrix.send_html(HOMESERVER, TOKEN, ROOM_ID, "summary", "<pre>summary</pre>")
    for plain, html in parts:
        matrix.send_html(HOMESERVER, TOKEN, ROOM_ID, plain, html, thread_root=root)

    # Should have been split into multiple PUTs (one for the summary + N parts)
    assert route.call_count >= 2

    first_body = json.loads(route.calls[0].request.content)
    assert "m.relates_to" not in first_body

    second_body = json.loads(route.calls[1].request.content)
    assert "m.relates_to" in second_body
