# Development Guidelines

This document contains critical information about working with this codebase. Follow these guidelines precisely.

## Core Development Rules

1. Package Management
   - ONLY use uv, NEVER pip
   - Installation: `uv add package`
   - Running tools: `uv run tool`
   - Upgrading: `uv add --dev package --upgrade-package package`
   - FORBIDDEN: `uv pip install`, `@latest` syntax

2. Code Quality
   - Type hints required for all code
   - Public APIs must have docstrings
   - Functions must be focused and small
   - Follow existing patterns exactly
   - Line length: 88 chars maximum

3. Testing Requirements
   - Framework: `uv run pytest`
   - Async testing: use anyio, not asyncio
   - Coverage: test edge cases and errors
   - New features require tests
   - Bug fixes require regression tests

4. Code Style
   - PEP 8 naming (snake_case for functions/variables)
   - Class names in PascalCase
   - Constants in UPPER_SNAKE_CASE
   - Document with docstrings
   - Use f-strings for formatting

## Development Philosophy

- **Simplicity**: Write simple, straightforward code
- **Readability**: Make code easy to understand
- **Performance**: Consider performance without sacrificing readability
- **Maintainability**: Write code that's easy to update
- **Testability**: Ensure code is testable
- **Reusability**: Create reusable components and functions
- **Less Code = Less Debt**: Minimize code footprint

## Coding Best Practices

- **Early Returns**: Use to avoid nested conditions
- **Descriptive Names**: Use clear variable/function names (prefix handlers with "handle")
- **Constants Over Functions**: Use constants where possible
- **DRY Code**: Don't repeat yourself
- **Functional Style**: Prefer functional, immutable approaches when not verbose
- **Minimal Changes**: Only modify code related to the task at hand
- **Function Ordering**: Define composing functions before their components
- **TODO Comments**: Mark issues in existing code with "TODO:" prefix
- **Simplicity**: Prioritize simplicity and readability over clever solutions
- **Build Iteratively** Start with minimal functionality and verify it works before adding complexity
- **Run Tests**: Test your code frequently with realistic inputs and validate outputs
- **Build Test Environments**: Create testing environments for components that are difficult to validate directly
- **Functional Code**: Use functional and stateless approaches where they improve clarity
- **Clean logic**: Keep core logic clean and push implementation details to the edges
- **File Organsiation**: Balance file organization with simplicity - use an appropriate number of files for the project scale

## System Architecture

An SMTP server (built on `aiosmtpd`) accepts mail on `SMTP_HOST:SMTP_PORT` and
forwards every message — regardless of recipient — to the single Matrix room
named by `MATRIX_ROOM_ID`. The Matrix token and room are resolved once at
startup, and posting uses the Matrix client-server HTTP API.

Each received mail is classified against the batching config (`CONFIG_PATH`,
YAML): it is matched top-to-bottom against `batch_emails` buckets (first match
wins), and a matched bucket is overridden to **send now** when any of its own or
the global `exceptions` match. Mail with no batch match is also sent now.

- **Send now:** post a 1-line summary as a root event, then the full rendered
  body as a threaded reply under it.
- **Held mail** is stored (raw bytes) in a SQLite bucket and posted later. An
  in-process asyncio scheduler flushes each bucket on its cron `schedule`,
  posting a digest header as a root event with each held mail's full body
  threaded underneath, then deleting the flushed rows.

Code lives in `src/smtp_to_matrix` and tests in `tests`.

## Core Components

- `src/smtp_to_matrix/server.py` — entry point (`main`) and the `aiosmtpd`
  `MatrixHandler`; reads env config, resolves Matrix credentials, classifies
  each message (send-now vs. held), and runs the SMTP listener alongside the
  scheduler.
- `src/smtp_to_matrix/config.py` — loads/validates the YAML config into typed
  `Config`/`Batch`/`Rule` models (compiled regexes, cron schedules) and
  `classify`s a mail into a batch name or send-now.
- `src/smtp_to_matrix/store.py` — SQLite `Store` for held mail
  (`init`/`add`/`pop`/`delete`) keyed by batch; stores raw bytes, re-rendered at
  flush.
- `src/smtp_to_matrix/scheduler.py` — in-process asyncio loop that sleeps to the
  soonest batch fire (via `croniter`), flushes due buckets as threaded digests,
  and reschedules.
- `src/smtp_to_matrix/message.py` — `render_email(raw, host)` parses an RFC-822
  message into `(plain, html)` bodies; `parse_meta`/`MailMeta` and
  `summary_line` build the classification metadata and the 1-line summary.
- `src/smtp_to_matrix/matrix.py` — synchronous `httpx` client for the Matrix
  client-server API (`resolve_token`, `resolve_room`, `send_html` with optional
  `thread_root` threading).
- `tests/` — `test_config.py`, `test_store.py`, `test_scheduler.py`,
  `test_matrix.py`, `test_message.py` (unit tests), and `test_server.py`
  (in-process SMTP-to-Matrix end-to-end with `respx`-mocked Matrix).

## Testing Conventions

### TDD Workflow
- Always write failing tests BEFORE implementation
- Use AAA pattern: Arrange-Act-Assert
- One assertion per test when possible
- Test names describe behavior: "should_return_empty_when_no_items"

### Test-First Rules
- When I ask for a feature, write tests first
- Tests should FAIL initially (no implementation exists)
- Only after tests are written, implement minimal code to pass

## Git workflow

- Create a descriptive commit message
- Create one short commented commit per phase, avoid long comments
- Run formatter and tests before committing

## Error Resolution

1. CI Failures
   - Fix order:
     1. Formatting
     2. Type errors
     3. Linting
   - Type errors:
     - Get full line context
     - Check Optional types
     - Add type narrowing
     - Verify function signatures

2. Common Issues
   - Line length:
     - Break strings with parentheses
     - Multi-line function calls
     - Split imports
   - Types:
     - Add None checks
     - Narrow string types
     - Match existing patterns

3. Best Practices
   - Check git status before commits
   - Run formatters before type checks
   - Keep changes minimal
   - Follow existing patterns
   - Document public APIs
   - Test thoroughly
