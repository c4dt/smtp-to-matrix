FROM python:3.12-slim

# uv provides reproducible, lockfile-driven installs (see CLAUDE.md).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install dependencies first for better layer caching, then the project.
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

# Configuration is supplied at runtime via MATRIX_* / SMTP_* env vars.
EXPOSE 25

ENTRYPOINT ["uv", "run", "smtp-to-matrix"]
