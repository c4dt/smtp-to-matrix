"""Tests for the Matrix client helper."""

import json

import httpx
import respx

from smtp_to_matrix import matrix

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
