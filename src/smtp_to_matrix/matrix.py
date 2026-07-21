"""Post an HTML message to a Matrix room over plain HTTP (room must be
unencrypted). Supports either a ready access token or password login.
"""

from __future__ import annotations

import os
import uuid
from urllib.parse import quote

import httpx

_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


def login(homeserver: str, user: str, password: str) -> tuple[str, str]:
    """Password-login; returns (access_token, user_id)."""
    resp = httpx.post(
        f"{homeserver}/_matrix/client/v3/login",
        json={
            "type": "m.login.password",
            "identifier": {"type": "m.id.user", "user": user},
            "password": password,
        },
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["access_token"], data["user_id"]


def joined_rooms(homeserver: str, token: str) -> list[str]:
    resp = httpx.get(
        f"{homeserver}/_matrix/client/v3/joined_rooms",
        headers={"Authorization": f"Bearer {token}"},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json().get("joined_rooms", [])


def resolve_room(homeserver: str, token: str, room: str) -> str:
    """Resolve a room alias (#name:server) to its internal id; ids pass through."""
    if room.startswith("!"):
        return room
    resp = httpx.get(
        f"{homeserver}/_matrix/client/v3/directory/room/{quote(room)}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["room_id"]


def send_html(
    homeserver: str,
    token: str,
    room_id: str,
    plain_body: str,
    html_body: str,
) -> str:
    # A unique transaction id per call: Matrix treats a repeated txn id as an
    # idempotent retry, so a content-derived id would drop duplicate messages.
    txn = uuid.uuid4().hex
    resp = httpx.put(
        f"{homeserver}/_matrix/client/v3/rooms/{quote(room_id)}/send/m.room.message/{txn}",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "msgtype": "m.text",
            "body": plain_body,
            "format": "org.matrix.custom.html",
            "formatted_body": html_body,
        },
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json().get("event_id", "")


def resolve_token(homeserver: str) -> str:
    """Prefer MATRIX_ACCESS_TOKEN; otherwise log in with MATRIX_LOGIN/MATRIX_PASS."""
    token = os.environ.get("MATRIX_ACCESS_TOKEN")
    if token:
        return token
    user = os.environ.get("MATRIX_LOGIN")
    password = os.environ.get("MATRIX_PASS")
    if not (user and password):
        raise RuntimeError(
            "Set MATRIX_ACCESS_TOKEN, or MATRIX_LOGIN + MATRIX_PASS for password login"
        )
    token, _ = login(homeserver, user, password)
    return token
