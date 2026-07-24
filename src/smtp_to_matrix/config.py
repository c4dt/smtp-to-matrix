"""Load and validate the batching config; classify mail into buckets.

The config (``CONFIG_PATH``, YAML) defines ``batch_emails`` buckets — each with a
cron ``schedule`` and a ``match_any`` list of rules — plus optional per-batch and
global ``exceptions``. Rules use ``re.search`` regexes on the ``host``, ``sender``,
``subject`` and ``body`` fields; set fields within a rule are ANDed, rules within
a ``match_any`` are ORed.
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
class Config:
    """Parsed configuration: the buckets and the global exceptions."""

    batches: list[Batch]
    exceptions: list[Rule]

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


def load(path: str | None) -> Config:
    """Load and validate the config; ``None`` yields an empty config."""
    if not path:
        return Config.empty()
    with open(path, encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    batches = [_build_batch(raw) for raw in data.get("batch_emails", [])]
    exceptions = _compile_rules((data.get("exceptions") or {}).get("match_any"))
    return Config(batches=batches, exceptions=exceptions)


def classify(config: Config, meta: MailMeta) -> str | None:
    """Return the batch name to hold this mail in, or ``None`` to send now.

    First matching batch wins; a matched batch is overridden to send-now when any
    of its own or the global exceptions match. No batch match sends now.
    """
    for batch in config.batches:
        if matches_any(batch.match, meta):
            if matches_any(batch.exceptions + config.exceptions, meta):
                return None
            return batch.name
    return None
