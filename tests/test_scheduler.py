"""Tests for the digest flush logic."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import anyio
import httpx
import pytest
import respx

from smtp_to_matrix import scheduler
from smtp_to_matrix.config import Batch
from smtp_to_matrix.message import MailMeta
from smtp_to_matrix.scheduler import flush_batch, run
from smtp_to_matrix.store import Store

HOMESERVER = "https://matrix.test"
ROOM_ID = "!room:test"
TOKEN = "tok_test"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


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
def test_flush_deletes_delivered_and_keeps_failed(tmp_path: Path) -> None:
    # Root ok, first reply ok, second reply 500 -> raise_for_status raises.
    respx.route(method="PUT", url__regex=r".*/send/m\.room\.message/.*").mock(
        side_effect=[
            httpx.Response(200, json={"event_id": "$root"}),
            httpx.Response(200, json={"event_id": "$r1"}),
            httpx.Response(500, json={"errcode": "M_UNKNOWN"}),
        ]
    )
    store = _seeded_store(tmp_path)
    batch = Batch(name="News", schedule="@daily", match=[])

    with pytest.raises(httpx.HTTPStatusError):
        flush_batch(HOMESERVER, TOKEN, ROOM_ID, store, batch)

    # First mail was delivered and deleted; the undelivered one is retained.
    remaining = store.pop("News")
    assert len(remaining) == 1
    assert b"second body" in remaining[0].raw


class _FakeCron:
    """Croniter stub: fires immediately once, then far in the future."""

    def __init__(self, expr: str, start: datetime) -> None:
        self._calls = 0

    def get_next(self, _type: type) -> datetime:
        self._calls += 1
        if self._calls == 1:
            return datetime.now() - timedelta(seconds=1)
        return datetime.now() + timedelta(days=1)


@pytest.mark.anyio
async def test_run_survives_failing_flush(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts: list[int] = []

    def boom(*args: object, **kwargs: object) -> None:
        attempts.append(1)
        raise RuntimeError("send failed")

    monkeypatch.setattr(scheduler, "flush_batch", boom)
    monkeypatch.setattr(scheduler, "croniter", _FakeCron)
    store = _seeded_store(tmp_path)
    batch = Batch(name="News", schedule="@daily", match=[])

    # run() never returns; the cancel scope stops it after the failing flush.
    with anyio.move_on_after(0.2):
        await run(HOMESERVER, TOKEN, ROOM_ID, store, [batch])

    # The flush was attempted and its failure did not propagate out of run().
    assert attempts


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
