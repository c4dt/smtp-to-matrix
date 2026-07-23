"""Tests for the digest flush logic."""

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import respx

from smtp_to_matrix.config import Batch
from smtp_to_matrix.message import MailMeta
from smtp_to_matrix.scheduler import flush_batch
from smtp_to_matrix.store import Store

HOMESERVER = "https://matrix.test"
ROOM_ID = "!room:test"
TOKEN = "tok_test"


def _meta(subject: str) -> MailMeta:
    return MailMeta(
        host="mailhost",
        sender="a@x",
        subject=subject,
        body="body",
        date=datetime(2023, 1, 1, tzinfo=UTC),
    )


def _seeded_store(tmp_path: Path) -> Store:
    store = Store(str(tmp_path / "pending.db"))
    store.init()
    store.add("News", b"Subject: one\n\nfirst body\n", _meta("one"))
    store.add("News", b"Subject: two\n\nsecond body\n", _meta("two"))
    return store


@respx.mock
def test_flush_posts_root_then_threaded_replies(tmp_path: Path) -> None:
    route = respx.route(method="PUT", url__regex=r".*/send/m\.room\.message/.*").mock(
        return_value=httpx.Response(200, json={"event_id": "$root"})
    )
    store = _seeded_store(tmp_path)
    batch = Batch(name="News", schedule="@daily", match=[])

    flush_batch(HOMESERVER, TOKEN, ROOM_ID, store, batch)

    # One root digest header + one reply per held mail.
    assert route.call_count == 3
    bodies = [json.loads(c.request.content) for c in route.calls]
    header = bodies[0]["body"]
    assert header.startswith("mailhost - News - ")
    assert header.endswith("- 2 messages")
    assert "m.relates_to" not in bodies[0]
    assert all(b["m.relates_to"]["event_id"] == "$root" for b in bodies[1:])
    assert "first body" in bodies[1]["body"]
    assert "second body" in bodies[2]["body"]


@respx.mock
def test_digest_header_counts_single_message(tmp_path: Path) -> None:
    route = respx.route(method="PUT", url__regex=r".*/send/m\.room\.message/.*").mock(
        return_value=httpx.Response(200, json={"event_id": "$root"})
    )
    store = Store(str(tmp_path / "pending.db"))
    store.init()
    store.add("News", b"Subject: one\n\nonly body\n", _meta("one"))
    batch = Batch(name="News", schedule="@daily", match=[])

    flush_batch(HOMESERVER, TOKEN, ROOM_ID, store, batch)

    header = json.loads(route.calls[0].request.content)["body"]
    assert header.endswith("- 1 message")


@respx.mock
def test_flush_clears_the_store(tmp_path: Path) -> None:
    respx.route(method="PUT", url__regex=r".*/send/m\.room\.message/.*").mock(
        return_value=httpx.Response(200, json={"event_id": "$root"})
    )
    store = _seeded_store(tmp_path)
    batch = Batch(name="News", schedule="@daily", match=[])

    flush_batch(HOMESERVER, TOKEN, ROOM_ID, store, batch)

    assert store.pop("News") == []


@respx.mock
def test_flush_empty_batch_posts_nothing(tmp_path: Path) -> None:
    route = respx.route(method="PUT", url__regex=r".*/send/m\.room\.message/.*").mock(
        return_value=httpx.Response(200, json={"event_id": "$root"})
    )
    store = Store(str(tmp_path / "pending.db"))
    store.init()
    batch = Batch(name="Empty", schedule="@daily", match=[])

    flush_batch(HOMESERVER, TOKEN, ROOM_ID, store, batch)

    assert not route.called
