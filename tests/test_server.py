"""In-process end-to-end test: SMTP in, mocked Matrix out."""

import smtplib
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
import respx
from aiosmtpd.controller import Controller

from smtp_to_matrix import config, matrix
from smtp_to_matrix.config import Config
from smtp_to_matrix.server import MatrixHandler
from smtp_to_matrix.store import Store

HOMESERVER = "https://matrix.test"
ROOM_ID = "!room:test"
TOKEN = "tok_test"
HOSTNAME = "mailhost"

BATCH_CONFIG = """\
batch_emails:
  - name: "News"
    schedule: "@daily"
    match_any:
      - subject: '(?i)newsletter'
    exceptions:
      match_any:
        - body: '(?i)urgent'
"""


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _store(tmp_path: Path) -> Store:
    store = Store(str(tmp_path / "pending.db"))
    store.init()
    return store


@contextmanager
def _server(cfg: Config, store: Store) -> Iterator[Controller]:
    handler = MatrixHandler(HOMESERVER, TOKEN, ROOM_ID, HOSTNAME, cfg, store)
    controller = Controller(handler, hostname="127.0.0.1", port=_free_port())
    controller.start()
    try:
        yield controller
    finally:
        controller.stop()


@pytest.fixture
def running_server(tmp_path: Path) -> Iterator[Controller]:
    with _server(Config.empty(), _store(tmp_path)) as controller:
        yield controller


def _port(controller: Controller) -> int:
    return controller.port


def _send(controller: Controller, message: str) -> None:
    with smtplib.SMTP("127.0.0.1", _port(controller)) as client:
        code, _ = client.docmd("HELO", "test")
        assert code == 250
        client.sendmail("ops@localhost", ["root@localhost"], message)


def _mock_send() -> respx.Route:
    return respx.route(method="PUT", url__regex=r".*/send/m\.room\.message/.*").mock(
        return_value=httpx.Response(200, json={"event_id": "$evt"})
    )


@respx.mock
def test_received_mail_is_posted_to_matrix(running_server: Controller) -> None:
    route = _mock_send()

    message = "Subject: alert\nFrom: ops@localhost\nTo: root@localhost\n\ndisk full\n"
    _send(running_server, message)

    # Send-now posts a summary root plus the full body as a threaded reply.
    assert route.call_count == 2
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


@respx.mock
def test_batch_mail_is_held_not_sent(tmp_path: Path) -> None:
    route = _mock_send()
    store = _store(tmp_path)
    cfg = config.load(str(_write(tmp_path, BATCH_CONFIG)))

    with _server(cfg, store) as controller:
        _send(controller, "Subject: Weekly Newsletter\n\ncontent\n")

    assert not route.called
    rows = store.pop("News")
    assert len(rows) == 1
    assert rows[0].subject == "Weekly Newsletter"


@respx.mock
def test_default_mail_is_sent_now(tmp_path: Path) -> None:
    route = _mock_send()
    store = _store(tmp_path)
    cfg = config.load(str(_write(tmp_path, BATCH_CONFIG)))

    with _server(cfg, store) as controller:
        _send(controller, "Subject: alert\n\ncontent\n")

    assert route.call_count == 2
    assert store.pop("News") == []


@respx.mock
def test_per_batch_exception_sends_now(tmp_path: Path) -> None:
    route = _mock_send()
    store = _store(tmp_path)
    cfg = config.load(str(_write(tmp_path, BATCH_CONFIG)))

    with _server(cfg, store) as controller:
        _send(controller, "Subject: Newsletter\n\nurgent: act now\n")

    assert route.call_count == 2
    assert store.pop("News") == []


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(text)
    return path


def test_resolve_token_prefers_access_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MATRIX_ACCESS_TOKEN", "from_env")
    assert matrix.resolve_token(HOMESERVER) == "from_env"
