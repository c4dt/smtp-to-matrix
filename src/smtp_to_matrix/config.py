"""Load and validate the batching and severity config; classify mail.

The config (``CONFIG_PATH``, YAML) defines ``batch_emails`` buckets — each with a
cron ``schedule`` and a ``match_any`` list of rules — plus optional per-batch and
global ``exceptions``. Rules use ``re.search`` regexes on the ``host``, ``sender``,
``subject`` and ``body`` fields; set fields within a rule are ANDed, rules within
a ``match_any`` are ORed.

A ``severity`` section maps mail to emoji-prefixed levels (error, info, …) using
the same rule mechanism. ``default`` and ``exception_severity`` name a level to
use when no rule matches or a batch exception triggers send-now.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import yaml
from croniter import croniter

from smtp_to_matrix.message import MailMeta

_FIELDS = ("host", "sender", "subject", "body")


@dataclass(frozen=True)
class Rule:
    """A single rule: compiled patterns for a subset of the mail fields."""

    patterns: dict[str, re.Pattern[str]]

    def matches(self, meta: MailMeta) -> bool:
        """True when every set field's pattern is found in the mail (AND)."""
        return all(
            pattern.search(getattr(meta, name))
            for name, pattern in self.patterns.items()
        )


@dataclass(frozen=True)
class Batch:
    """A named bucket flushed on ``schedule`` (a cron expression)."""

    name: str
    schedule: str
    match: list[Rule]
    exceptions: list[Rule] = field(default_factory=list)


@dataclass(frozen=True)
class Severity:
    """A named severity level with an emoji prefix and matching rules."""

    name: str
    emoji: str
    match: list[Rule]


@dataclass(frozen=True)
class Classification:
    """Result of classifying a mail: which batch (if any) and why send-now.

    ``batch`` is ``None`` when the mail should be sent immediately. ``exception``
    is ``True`` when a batch matched but an exception overrode it to send-now.
    """

    batch: str | None
    exception: bool


@dataclass(frozen=True)
class Config:
    """Parsed configuration: batches, exceptions and severity levels."""

    batches: list[Batch]
    exceptions: list[Rule]
    levels: list[Severity] = field(default_factory=list)
    default_severity: Severity | None = None
    exception_severity: Severity | None = None

    @classmethod
    def empty(cls) -> Config:
        """A config with no batches — every mail is sent immediately."""
        return cls(batches=[], exceptions=[])


def matches_any(rules: list[Rule], meta: MailMeta) -> bool:
    """True when any rule matches (OR across a ``match_any`` list)."""
    return any(rule.matches(meta) for rule in rules)


def _compile_rule(raw: dict[str, str]) -> Rule:
    """Compile one rule's field regexes, raising ``RuntimeError`` on bad regex."""
    patterns: dict[str, re.Pattern[str]] = {}
    for name in _FIELDS:
        if name in raw:
            try:
                patterns[name] = re.compile(raw[name])
            except re.error as exc:
                raise RuntimeError(f"invalid regex for {name!r}: {exc}") from exc
    return Rule(patterns=patterns)


def _compile_rules(match_any: list[dict[str, str]] | None) -> list[Rule]:
    return [_compile_rule(raw) for raw in match_any or []]


def _build_batch(raw: dict[str, object]) -> Batch:
    schedule = str(raw["schedule"])
    if not croniter.is_valid(schedule):
        raise RuntimeError(f"invalid cron schedule: {schedule!r}")
    exceptions = raw.get("exceptions") or {}
    return Batch(
        name=str(raw["name"]),
        schedule=schedule,
        match=_compile_rules(raw.get("match_any")),  # type: ignore[arg-type]
        exceptions=_compile_rules(exceptions.get("match_any")),  # type: ignore[union-attr]
    )


def _build_severity(raw: dict[str, object]) -> Severity:
    return Severity(
        name=str(raw["name"]),
        emoji=str(raw["emoji"]),
        match=_compile_rules(raw.get("match_any")),  # type: ignore[arg-type]
    )


def _find_severity(levels: list[Severity], name: str | None) -> Severity | None:
    """Return the level with ``name`` or ``None`` when ``name`` is falsy."""
    if not name:
        return None
    for level in levels:
        if level.name == name:
            return level
    raise RuntimeError(f"unknown severity level: {name!r}")


def load(path: str | None) -> Config:
    """Load and validate the config; ``None`` yields an empty config."""
    if not path:
        return Config.empty()
    with open(path, encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    batches = [_build_batch(raw) for raw in data.get("batch_emails", [])]
    exceptions = _compile_rules((data.get("exceptions") or {}).get("match_any"))
    levels = [
        _build_severity(raw)  # type: ignore[arg-type]
        for raw in (data.get("severity") or {}).get("levels", [])
    ]
    sev_raw = data.get("severity") or {}
    default_sev = _find_severity(levels, sev_raw.get("default"))  # type: ignore[arg-type]
    exception_sev = _find_severity(  # type: ignore[arg-type]
        levels, sev_raw.get("exception_severity")
    )
    return Config(
        batches=batches,
        exceptions=exceptions,
        levels=levels,
        default_severity=default_sev,
        exception_severity=exception_sev,
    )


def classify(config: Config, meta: MailMeta) -> Classification:
    """Classify a mail: which batch to hold it in, or send-now with reason.

    First matching batch wins; a matched batch is overridden to send-now when any
    of its own or the global exceptions match. No batch match sends now.
    """
    for batch in config.batches:
        if matches_any(batch.match, meta):
            if matches_any(batch.exceptions + config.exceptions, meta):
                return Classification(batch=None, exception=True)
            return Classification(batch=batch.name, exception=False)
    return Classification(batch=None, exception=False)


def classify_severity(config: Config, meta: MailMeta) -> Severity | None:
    """Return the first matching severity level, or ``None`` when none match."""
    for level in config.levels:
        if matches_any(level.match, meta):
            return level
    return None
