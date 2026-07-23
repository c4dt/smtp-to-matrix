"""Unit tests for config loading, rule matching and classification."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from smtp_to_matrix import config
from smtp_to_matrix.message import MailMeta

NEWSLETTERS = """\
batch_emails:
  - name: "Newsletters"
    schedule: "0 8 * * *"
    match_any:
      - sender: '.*@newsletter\\.example\\.com'
      - subject: '(?i)weekly digest'
      - sender: 'monitoring@.*'
        subject: '(?i)backup'
    exceptions:
      match_any:
        - body: '(?i)\\bERROR\\b'
exceptions:
  match_any:
    - body: '(?i)\\berror\\b'
"""


def _meta(
    host: str = "mailhost",
    sender: str = "",
    subject: str = "",
    body: str = "",
) -> MailMeta:
    return MailMeta(
        host=host,
        sender=sender,
        subject=subject,
        body=body,
        date=datetime(2023, 1, 1, tzinfo=UTC),
    )


def _write(tmp_path: Path, text: str) -> str:
    path = tmp_path / "config.yaml"
    path.write_text(text)
    return str(path)


def test_empty_when_path_is_none() -> None:
    cfg = config.load(None)
    assert cfg.batches == []
    assert cfg.exceptions == []


def test_loads_batch_and_schedule(tmp_path: Path) -> None:
    cfg = config.load(_write(tmp_path, NEWSLETTERS))
    assert len(cfg.batches) == 1
    assert cfg.batches[0].name == "Newsletters"
    assert cfg.batches[0].schedule == "0 8 * * *"


def test_sender_only_rule_matches(tmp_path: Path) -> None:
    cfg = config.load(_write(tmp_path, NEWSLETTERS))
    meta = _meta(sender="news@newsletter.example.com")
    assert config.classify(cfg, meta) == "Newsletters"


def test_subject_only_rule_matches(tmp_path: Path) -> None:
    cfg = config.load(_write(tmp_path, NEWSLETTERS))
    meta = _meta(sender="someone@else.com", subject="Our Weekly Digest")
    assert config.classify(cfg, meta) == "Newsletters"


def test_rule_fields_are_anded(tmp_path: Path) -> None:
    cfg = config.load(_write(tmp_path, NEWSLETTERS))
    # sender matches the AND rule but subject does not -> that rule fails, and no
    # other rule matches this sender.
    meta = _meta(sender="monitoring@host", subject="unrelated")
    assert config.classify(cfg, meta) is None
    meta = _meta(sender="monitoring@host", subject="nightly BACKUP")
    assert config.classify(cfg, meta) == "Newsletters"


def test_no_match_is_send_now(tmp_path: Path) -> None:
    cfg = config.load(_write(tmp_path, NEWSLETTERS))
    assert config.classify(cfg, _meta(sender="a@b.com")) is None


def test_global_exception_overrides_hold(tmp_path: Path) -> None:
    cfg = config.load(_write(tmp_path, NEWSLETTERS))
    meta = _meta(sender="news@newsletter.example.com", body="an error happened")
    assert config.classify(cfg, meta) is None


def test_per_batch_exception_overrides_its_batch(tmp_path: Path) -> None:
    cfg = config.load(_write(tmp_path, NEWSLETTERS))
    meta = _meta(sender="news@newsletter.example.com", body="ERROR: disk full")
    assert config.classify(cfg, meta) is None


def test_first_batch_wins(tmp_path: Path) -> None:
    text = """\
batch_emails:
  - name: "First"
    schedule: "@daily"
    match_any:
      - sender: '.*@x\\.com'
  - name: "Second"
    schedule: "@daily"
    match_any:
      - sender: 'a@x\\.com'
"""
    cfg = config.load(_write(tmp_path, text))
    assert config.classify(cfg, _meta(sender="a@x.com")) == "First"


def test_bad_regex_raises(tmp_path: Path) -> None:
    text = """\
batch_emails:
  - name: "Bad"
    schedule: "@daily"
    match_any:
      - sender: '('
"""
    with pytest.raises(RuntimeError):
        config.load(_write(tmp_path, text))


def test_bad_cron_raises(tmp_path: Path) -> None:
    text = """\
batch_emails:
  - name: "Bad"
    schedule: "not a cron"
    match_any:
      - sender: '.*'
"""
    with pytest.raises(RuntimeError):
        config.load(_write(tmp_path, text))
