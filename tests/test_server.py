"""In-process end-to-end test: SMTP in, mocked Matrix out."""

import smtplib
import socket
from collections.abc import Iterator

import httpx
import pytest
import respx
from aiosmtpd.controller import Controller

from smtp_to_matrix import matrix
from smtp_to_matrix.server import MatrixHandler

HOMESERVER = "https://matrix.test"
ROOM_ID = "!room:test"
TOKEN = "tok_test"
HOSTNAME = "mailhost"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def running_server() -> Iterator[Controller]:
    handler = MatrixHandler(HOMESERVER, TOKEN, ROOM_ID, HOSTNAME)
    controller = Controller(handler, hostname="127.0.0.1", port=_free_port())
    controller.start()
    try:
        yield controller
    finally:
        controller.stop()


def _port(controller: Controller) -> int:
    return controller.port


@respx.mock
def test_received_mail_is_posted_to_matrix(running_server: Controller) -> None:
    route = respx.route(method="PUT", url__regex=r".*/send/m\.room\.message/.*").mock(
        return_value=httpx.Response(200, json={"event_id": "$evt"})
    )

    message = "Subject: alert\nFrom: ops@localhost\nTo: root@localhost\n\ndisk full\n"
    with smtplib.SMTP("127.0.0.1", _port(running_server)) as client:
        code, _ = client.docmd("HELO", "test")
        assert code == 250
        client.sendmail("ops@localhost", ["root@localhost"], message)

    assert route.called
    sent = route.calls.last.request
    assert "/rooms/%21room%3Atest/send/" in str(sent.url)
    body = sent.content.decode()
    assert "disk full" in body
    assert "alert" in body
    assert f"Host: {HOSTNAME}" in body


@respx.mock
def test_matrix_failure_returns_temporary_error(running_server: Controller) -> None:
    respx.route(method="PUT", url__regex=r".*/send/m\.room\.message/.*").mock(
        return_value=httpx.Response(502)
    )

    message = "Subject: x\n\nbody\n"
    with smtplib.SMTP("127.0.0.1", _port(running_server)) as client:
        client.helo("test")
        with pytest.raises(smtplib.SMTPDataError) as excinfo:
            client.sendmail("ops@localhost", ["root@localhost"], message)
    assert excinfo.value.smtp_code == 451


def test_resolve_token_prefers_access_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MATRIX_ACCESS_TOKEN", "from_env")
    assert matrix.resolve_token(HOMESERVER) == "from_env"
