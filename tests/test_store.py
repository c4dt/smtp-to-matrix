"""Tests for the SQLite hold-and-flush store."""

from datetime import UTC, datetime
from pathlib import Path

from smtp_to_matrix.message import MailMeta
from smtp_to_matrix.store import Store


def _meta(sender: str = "a@x", subject: str = "hi") -> MailMeta:
    return MailMeta(
        host="mailhost",
        sender=sender,
        subject=subject,
        body="body",
        date=datetime(2023, 1, 1, tzinfo=UTC),
    )


def _store(tmp_path: Path) -> Store:
    store = Store(str(tmp_path / "pending.db"))
    store.init()
    return store


def test_add_pop_roundtrip_preserves_raw(tmp_path: Path) -> None:
    store = _store(tmp_path)
    raw = b"Subject: hi\n\n\x00\x01 raw bytes"
    store.add("Newsletters", raw, _meta())

    rows = store.pop("Newsletters")
    assert len(rows) == 1
    assert rows[0].raw == raw
    assert rows[0].host == "mailhost"
    assert rows[0].subject == "hi"


def test_pop_isolates_by_batch(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.add("A", b"one", _meta(subject="one"))
    store.add("B", b"two", _meta(subject="two"))

    assert [r.raw for r in store.pop("A")] == [b"one"]
    assert [r.raw for r in store.pop("B")] == [b"two"]


def test_pop_orders_by_insertion(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.add("A", b"first", _meta())
    store.add("A", b"second", _meta())
    assert [r.raw for r in store.pop("A")] == [b"first", b"second"]


def test_delete_removes_rows(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.add("A", b"one", _meta())
    store.add("A", b"two", _meta())

    rows = store.pop("A")
    store.delete([rows[0].id])
    remaining = store.pop("A")
    assert [r.raw for r in remaining] == [b"two"]
