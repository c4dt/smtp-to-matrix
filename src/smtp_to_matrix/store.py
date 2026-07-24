"""SQLite store for mail held in a batch until its digest is flushed.

Raw bytes are stored verbatim and re-rendered at flush time. A fresh connection
is opened per call so the store is safe to share between the SMTP handler thread
(which adds) and the scheduler thread (which pops and deletes).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from smtp_to_matrix.message import MailMeta

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pending_mail (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at TEXT NOT NULL,
    host TEXT NOT NULL,
    sender TEXT NOT NULL,
    subject TEXT NOT NULL,
    batch TEXT NOT NULL,
    raw BLOB NOT NULL
)
"""


@dataclass(frozen=True)
class Row:
    """A held mail row: its id, metadata and the original raw bytes."""

    id: int
    host: str
    sender: str
    subject: str
    date: datetime
    raw: bytes


class Store:
    """A SQLite-backed hold for batched mail."""

    def __init__(self, path: str) -> None:
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def init(self) -> None:
        """Create the ``pending_mail`` table if it does not exist."""
        with self._connect() as conn:
            conn.execute(_SCHEMA)

    def add(self, batch: str, raw: bytes, meta: MailMeta) -> None:
        """Hold a mail's raw bytes and metadata under ``batch``."""
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO pending_mail "
                "(received_at, host, sender, subject, batch, raw) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    meta.date.isoformat(),
                    meta.host,
                    meta.sender,
                    meta.subject,
                    batch,
                    raw,
                ),
            )

    def pop(self, batch: str) -> list[Row]:
        """Return all held rows for ``batch`` in insertion order (no delete)."""
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT id, host, sender, subject, received_at, raw FROM pending_mail "
                "WHERE batch = ? ORDER BY id",
                (batch,),
            )
            return [
                Row(
                    id=row[0],
                    host=row[1],
                    sender=row[2],
                    subject=row[3],
                    date=datetime.fromisoformat(row[4]),
                    raw=row[5],
                )
                for row in cursor.fetchall()
            ]

    def delete(self, ids: list[int]) -> None:
        """Delete the rows with the given ids."""
        if not ids:
            return
        placeholders = ",".join("?" * len(ids))
        with self._connect() as conn:
            conn.execute(f"DELETE FROM pending_mail WHERE id IN ({placeholders})", ids)
