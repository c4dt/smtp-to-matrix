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

SEVERITY = """\
severity:
  default: "info"
  exception_severity: "error"
  levels:
    - name: "error"
      emoji: "\\u26a0\\ufe0f"
      match_any:
        - body: '(?i)\\bERROR\\b'
    - name: "success"
      emoji: "\\u2705"
      match_any:
        - subject: '(?i)\\bsuccess\\b'
    - name: "info"
      emoji: "\\u2139\\ufe0f"
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
    assert cfg.levels == []
    assert cfg.default_severity is None
    assert cfg.exception_severity is None


def test_loads_batch_and_schedule(tmp_path: Path) -> None:
    cfg = config.load(_write(tmp_path, NEWSLETTERS))
    assert len(cfg.batches) == 1
    assert cfg.batches[0].name == "Newsletters"
    assert cfg.batches[0].schedule == "0 8 * * *"


def test_sender_only_rule_matches(tmp_path: Path) -> None:
    cfg = config.load(_write(tmp_path, NEWSLETTERS))
    meta = _meta(sender="news@newsletter.example.com")
    assert config.classify(cfg, meta) == config.Classification(
        batch="Newsletters", exception=False
    )


def test_subject_only_rule_matches(tmp_path: Path) -> None:
    cfg = config.load(_write(tmp_path, NEWSLETTERS))
    meta = _meta(sender="someone@else.com", subject="Our Weekly Digest")
    assert config.classify(cfg, meta) == config.Classification(
        batch="Newsletters", exception=False
    )


def test_rule_fields_are_anded(tmp_path: Path) -> None:
    cfg = config.load(_write(tmp_path, NEWSLETTERS))
    # sender matches the AND rule but subject does not -> that rule fails, and no
    # other rule matches this sender.
    meta = _meta(sender="monitoring@host", subject="unrelated")
    assert config.classify(cfg, meta) == config.Classification(
        batch=None, exception=False
    )
    meta = _meta(sender="monitoring@host", subject="nightly BACKUP")
    assert config.classify(cfg, meta) == config.Classification(
        batch="Newsletters", exception=False
    )


def test_no_match_is_send_now(tmp_path: Path) -> None:
    cfg = config.load(_write(tmp_path, NEWSLETTERS))
    assert config.classify(cfg, _meta(sender="a@b.com")) == config.Classification(
        batch=None, exception=False
    )


def test_global_exception_overrides_hold(tmp_path: Path) -> None:
    cfg = config.load(_write(tmp_path, NEWSLETTERS))
    meta = _meta(sender="news@newsletter.example.com", body="an error happened")
    assert config.classify(cfg, meta) == config.Classification(
        batch=None, exception=True
    )


def test_per_batch_exception_overrides_its_batch(tmp_path: Path) -> None:
    cfg = config.load(_write(tmp_path, NEWSLETTERS))
    meta = _meta(sender="news@newsletter.example.com", body="ERROR: disk full")
    assert config.classify(cfg, meta) == config.Classification(
        batch=None, exception=True
    )


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
    assert config.classify(cfg, _meta(sender="a@x.com")) == config.Classification(
        batch="First", exception=False
    )


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


# --- severity tests ---


def test_loads_severity_levels(tmp_path: Path) -> None:
    cfg = config.load(_write(tmp_path, SEVERITY))
    assert len(cfg.levels) == 3
    assert cfg.levels[0].name == "error"
    assert cfg.levels[0].emoji == "⚠️"
    assert cfg.levels[1].name == "success"
    assert cfg.levels[1].emoji == "✅"
    assert cfg.levels[2].name == "info"
    assert cfg.levels[2].emoji == "ℹ️"


def test_loads_default_and_exception_severity(tmp_path: Path) -> None:
    cfg = config.load(_write(tmp_path, SEVERITY))
    assert cfg.default_severity is not None
    assert cfg.default_severity.name == "info"
    assert cfg.exception_severity is not None
    assert cfg.exception_severity.name == "error"


def test_classify_severity_matches_error(tmp_path: Path) -> None:
    cfg = config.load(_write(tmp_path, SEVERITY))
    meta = _meta(body="something ERROR happened")
    sev = config.classify_severity(cfg, meta)
    assert sev is not None
    assert sev.name == "error"
    assert sev.emoji == "⚠️"


def test_classify_severity_matches_success(tmp_path: Path) -> None:
    cfg = config.load(_write(tmp_path, SEVERITY))
    meta = _meta(subject="Operation success")
    sev = config.classify_severity(cfg, meta)
    assert sev is not None
    assert sev.name == "success"
    assert sev.emoji == "✅"


def test_classify_severity_returns_none_when_no_match(tmp_path: Path) -> None:
    cfg = config.load(_write(tmp_path, SEVERITY))
    meta = _meta(subject="hello", body="just info")
    assert config.classify_severity(cfg, meta) is None


def test_classify_severity_first_match_wins(tmp_path: Path) -> None:
    text = """\
severity:
  levels:
    - name: "first"
      emoji: "1️⃣"
      match_any:
        - subject: '.*'
    - name: "second"
      emoji: "2️⃣"
      match_any:
        - subject: '.*'
"""
    cfg = config.load(_write(tmp_path, text))
    sev = config.classify_severity(cfg, _meta(subject="anything"))
    assert sev is not None
    assert sev.name == "first"


def test_classify_severity_no_levels_returns_none(tmp_path: Path) -> None:
    cfg = config.load(None)
    assert config.classify_severity(cfg, _meta(body="ERROR")) is None


def test_severity_default_references_unknown_name(tmp_path: Path) -> None:
    text = """\
severity:
  default: "nonexistent"
  levels:
    - name: "info"
      emoji: "ℹ️"
"""
    with pytest.raises(ValueError):
        config.load(_write(tmp_path, text))


def test_severity_exception_references_unknown_name(tmp_path: Path) -> None:
    text = """\
severity:
  exception_severity: "nonexistent"
  levels:
    - name: "info"
      emoji: "ℹ️"
"""
    with pytest.raises(ValueError):
        config.load(_write(tmp_path, text))
