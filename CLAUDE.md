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
startup; each received message is rendered to plain-text + HTML and posted via
the Matrix client-server HTTP API. Code lives in `src/smtp_to_matrix` and tests
in `tests`.

## Core Components

- `src/smtp_to_matrix/server.py` — entry point (`main`) and the `aiosmtpd`
  `MatrixHandler`; reads env config, runs the listener, forwards each message to
  Matrix off the event loop.
- `src/smtp_to_matrix/message.py` — `render_email(raw)` parses an RFC-822 message
  into `(plain, html)` bodies.
- `src/smtp_to_matrix/matrix.py` — synchronous `httpx` client for the Matrix
  client-server API (`resolve_token`, `resolve_room`, `send_html`).
- `tests/` — `test_message.py` (rendering unit tests) and `test_server.py`
  (in-process SMTP-to-Matrix end-to-end with `respx`-mocked Matrix).
