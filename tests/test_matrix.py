"""Tests for the Matrix client helper."""

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
