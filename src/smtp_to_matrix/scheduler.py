"""In-process scheduler that flushes each batch's digest on its cron schedule.

A digest is posted as a root event carrying the batch name, with each held mail's
full body threaded underneath it; flushed rows are then deleted. Waiting uses the
event loop; the blocking Matrix HTTP calls run in a worker thread.
"""

from __future__ import annotations

import asyncio
import html
import sys
import time
from datetime import datetime

from croniter import croniter

from smtp_to_matrix import matrix
from smtp_to_matrix.config import Batch, Config
from smtp_to_matrix.message import render_email
from smtp_to_matrix.store import Row, Store


def _log(message: str) -> None:
    """Write a prefixed line to stderr."""
    print(f"smtp-to-matrix: {message}", file=sys.stderr)


def _digest_header(batch: Batch, rows: list[Row]) -> str:
    """Summarise a digest: ``date until otherdate - host - title - N message(s)``."""
    dates = sorted(row.date.astimezone() for row in rows)
    span = dates[0].strftime("%Y-%m-%d %H:%M")
    if dates[0] != dates[-1]:
        span += f" until {dates[-1]:%Y-%m-%d %H:%M}"
    count = len(rows)
    noun = "message" if count == 1 else "messages"
    return f"{span} - {rows[0].host} - {batch.name} - {count} {noun}"


def flush_batch(
    homeserver: str,
    token: str,
    room_id: str,
    store: Store,
    cfg: Config,
    batch: Batch,
) -> None:
    """Post a batch's held mail as a threaded digest, then delete the rows."""
    rows = store.pop(batch.name)
    if not rows:
        return
    count = len(rows)
    noun = "message" if count == 1 else "messages"
    _log(f"sending batch {batch.name!r} digest: {count} {noun}")
    header = _digest_header(batch, rows)
    if cfg.default_severity is not None:
        header = f"{cfg.default_severity.emoji} {header}"
    root = matrix.send_html(
        homeserver, token, room_id, header, f"{html.escape(header)}"
    )
    for row in rows:
        messages = render_email(row.raw, row.host)
        _log(f"sending message {row.id} in batch {batch.name!r}")
        for plain, html_body in messages:
            time.sleep(1)
            try:
                matrix.send_html(
                    homeserver,
                    token,
                    room_id,
                    plain,
                    html_body,
                    thread_root=root,
                )
            except Exception:
                _log(f"failed to send message {row.id}. Trying again in 1 minute")
                time.sleep(60)
                matrix.send_html(
                    homeserver,
                    token,
                    room_id,
                    plain,
                    html_body,
                    thread_root=root,
                )

        # Delete right after a successful send so a later failure can't resurrect
        # an already-delivered mail on the next flush.
        store.delete([row.id])


async def run(
    homeserver: str,
    token: str,
    room_id: str,
    store: Store,
    cfg: Config,
) -> None:
    """Sleep until the soonest batch fires, flush the due batches, repeat."""
    batches = cfg.batches
    schedules = {
        batch.name: croniter(batch.schedule, datetime.now()) for batch in batches
    }
    next_fire = {name: it.get_next(datetime) for name, it in schedules.items()}

    while True:
        soonest = min(next_fire.values())
        delay = (soonest - datetime.now()).total_seconds()
        if delay > 0:
            await asyncio.sleep(delay)
        now = datetime.now()
        for batch in batches:
            if next_fire[batch.name] <= now:
                try:
                    await asyncio.to_thread(
                        flush_batch,
                        homeserver,
                        token,
                        room_id,
                        store,
                        cfg,
                        batch,
                    )
                except Exception as exc:  # noqa: BLE001 - one bad flush must not kill the loop
                    _log(f"flush failed for {batch.name!r}: {exc}")
                next_fire[batch.name] = schedules[batch.name].get_next(datetime)
