"""In-process scheduler that flushes each batch's digest on its cron schedule.

A digest is posted as a root event carrying the batch name, with each held mail's
full body threaded underneath it; flushed rows are then deleted. Waiting uses the
event loop; the blocking Matrix HTTP calls run in a worker thread.
"""

from __future__ import annotations

import asyncio
import html
from datetime import datetime

from croniter import croniter

from smtp_to_matrix import matrix
from smtp_to_matrix.config import Batch
from smtp_to_matrix.message import render_email
from smtp_to_matrix.store import Row, Store


def _digest_header(batch: Batch, rows: list[Row]) -> str:
    """Summarise a digest: ``host - title - first until last - N message(s)``."""
    dates = sorted(row.date.astimezone() for row in rows)
    span = dates[0].strftime("%Y-%m-%d %H:%M")
    if dates[0] != dates[-1]:
        span += f" until {dates[-1]:%Y-%m-%d %H:%M}"
    count = len(rows)
    noun = "message" if count == 1 else "messages"
    return f"{rows[0].host} - {batch.name} - {span} - {count} {noun}"


def flush_batch(
    homeserver: str,
    token: str,
    room_id: str,
    store: Store,
    batch: Batch,
) -> None:
    """Post a batch's held mail as a threaded digest, then delete the rows."""
    rows = store.pop(batch.name)
    if not rows:
        return
    header = _digest_header(batch, rows)
    root = matrix.send_html(
        homeserver, token, room_id, header, f"{html.escape(header)}"
    )
    for row in rows:
        plain, html_body = render_email(row.raw, row.host)
        matrix.send_html(homeserver, token, room_id, plain, html_body, thread_root=root)
    store.delete([row.id for row in rows])


async def run(
    homeserver: str,
    token: str,
    room_id: str,
    store: Store,
    batches: list[Batch],
) -> None:
    """Sleep until the soonest batch fires, flush the due batches, repeat."""
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
                await asyncio.to_thread(
                    flush_batch, homeserver, token, room_id, store, batch
                )
                next_fire[batch.name] = schedules[batch.name].get_next(datetime)
