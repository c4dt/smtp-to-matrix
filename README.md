# smtp-to-matrix

An SMTP server that forwards every message it receives — regardless of recipient
address — to a single Matrix room. Point any tool that sends mail (cron, `mail`,
monitoring alerts, a printer) at it and the messages show up in Matrix.

Built on [aiosmtpd](https://aiosmtpd.aio-libs.org/). The listener is plain SMTP
with no authentication or TLS, so run it on a trusted network (or behind a real
MTA). The target Matrix room must be **unencrypted**.

## Configuration

The server reads its configuration from environment variables:

| Variable                | Required | Description                                                            |
| ----------------------- | -------- | ---------------------------------------------------------------------- |
| `MATRIX_HOMESERVER_URL` | yes      | Base URL of the homeserver, e.g. `https://matrix.example.org`.         |
| `MATRIX_ROOM_ID`        | yes      | Target room id `!id:server` or alias `#name:server`.                   |
| `MATRIX_ACCESS_TOKEN`   | either   | A ready access token. Preferred over login.                            |
| `MATRIX_LOGIN`          | either   | Username for password login (used when no access token is set).        |
| `MATRIX_PASS`           | either   | Password for password login.                                           |
| `MATRIX_HOST_LABEL`     | no       | Label for the `Host:` line of each message. Default: machine hostname. |
| `SMTP_HOST`             | no       | Bind address for the listener. Default `0.0.0.0`.                      |
| `SMTP_PORT`             | no       | Listener port. Default `25` (needs root/`CAP_NET_BIND_SERVICE`).       |
| `CONFIG_PATH`           | no       | Path to the batching config (see below). Unset: every mail sent now.   |
| `DB_PATH`               | no       | SQLite file for batched mail. Default `pending_mail.db`.               |

For development, copy the example file, fill it in, and export it into your shell:

```sh
cp .env.example .env
set -a; . ./.env; set +a
uv run smtp-to-matrix
```

## Development environment

This repo uses [devbox](https://www.jetify.com/devbox) for the toolchain
(`uv`, Python, `prettier`) and [uv](https://docs.astral.sh/uv/) for Python
dependencies.

```sh
devbox shell        # enters the environment and runs `uv sync`
devbox run start    # uv run smtp-to-matrix
devbox run test     # uv run pytest
devbox run lint     # ruff check + ruff format --check + prettier --check
devbox run format   # ruff --fix + ruff format + prettier --write
```

Without devbox, `uv` alone is enough:

```sh
uv sync
uv run pytest
```

Python code is formatted and linted with **Ruff**; **Prettier** formats only the
non-Python files (JSON / YAML / Markdown).

## Usage

Start the server with the `MATRIX_*` variables set (e.g. via `.env`):

```sh
uv run smtp-to-matrix
```

It resolves the Matrix token and room once at startup, then listens for mail.
Every received message is rendered — the receiving server's hostname on the first
line (`Host: ...`), then a `From`/`To`/`Subject` header block, then the text body.

By default each message is posted immediately as a **one-line summary**
(`host - date - sender - subject`) with the full rendered body as a **threaded
reply** underneath, so the room stays scannable.

## Summaries, batching & digests

Set `CONFIG_PATH` to a YAML file to hold selected mail in named buckets and post
each bucket as a scheduled digest instead of immediately. See
[`config.example.yaml`](config.example.yaml) for the full format.

Each received mail is classified in order:

1. Match against `batch_emails` top-to-bottom — **first match wins**.
2. If a batch matched, check that batch's `exceptions` plus the global
   `exceptions` — if any match, **send now**; otherwise **hold** in that bucket.
3. No batch matched — **send now** (the default).

Rules use `re.search`; within a rule the set fields (`host`, `sender`,
`subject`, `body`) are ANDed, and rules within a `match_any` list are ORed. Each
batch has a cron `schedule` (5-field or `@macros`, server local time); when it
fires, the held mail is posted as a digest (the batch name as the root event,
each held body threaded under it) and the bucket is cleared. Held mail lives in
the SQLite file at `DB_PATH` and survives restarts.

## Docker

A container image is built and published to the GitHub Container Registry on
every push to `main` (see `.github/workflows/docker.yml`). Supply the
configuration as environment variables and publish the SMTP port:

```sh
docker run --rm \
  -e MATRIX_HOMESERVER_URL=https://matrix.example.org \
  -e MATRIX_ROOM_ID='!roomid:example.org' \
  -e MATRIX_ACCESS_TOKEN=... \
  -p 25:25 \
  ghcr.io/c4dt/smtp-to-matrix:latest
```

To build the image locally instead:

```sh
docker build -t smtp-to-matrix .
```

## Installation as a System Mailer for Ubuntu

### smtp-to-matrix installation

> Docker must be installed as a pre-requisite

Create a smtp-to-matrix user

```bash
useradd -m smtp-to-matrix
usermod -aG docker smtp-to-matrix
```

As the user, create the env file (fill out the empty env variables, use password or sharedsecret)

```bash
cp .env.example .env
vim .env
```

Create a docker-compose file:

```bash
cat <<EOF > compose.yml
services:
  smtp-to-matrix:
    # Can bind to 25
    cap_add:
      - NET_BIND_SERVICE
    ports:
      - 25:25
    env_file: ./.env
    volumes:
      - ./config.yaml:/etc/smtp-to-matrix/config.yaml
      - ./data:/app/data
    environment:
      - MATRIX_HOST_LABEL=${HOSTNAME}
      - CONFIG_PATH=/etc/smtp-to-matrix/config.yaml
      - DB_PATH=data/pending_mail.db
    image: ghcr.io/c4dt/smtp-to-matrix:latest
EOF
```

Start the service

```bash
docker compose up -d
```

### Sendmail configuration

To forward all mails from our server to smtp-to-matrix we use the msmtp SMTP client and configure postmoogle as the server.

```bash
apt install msmtp msmtp-mta
```

> ⚠️ We will replace the installed postfix installation and need to make sure we don’t break existing configuration.

Configure MSMTP to send with postmoogle

```bash
cat <<EOF > /etc/msmtprc
defaults
auth off
tls off
auto_from on

account matrix-to-smtp
host 127.0.0.1
port 25

account default : matrix-to-smtp
EOF
```

Update permissions

```bash
chmod 644 /etc/msmtprc  # Users need read permissions in order to send mails
```

## Smoke test

With the server running, send it a message from another shell. With
[swaks](https://github.com/jetmore/swaks):

```sh
swaks --to any@localhost --server localhost:25 --header "Subject: hello" --body "it works"
```

Or with plain Python:

```sh
python - <<'PY'
import smtplib
msg = "Subject: hello\nFrom: me@localhost\nTo: any@localhost\n\nit works\n"
with smtplib.SMTP("localhost", 25) as s:
    s.sendmail("me@localhost", ["any@localhost"], msg)
PY
```

The message should appear in your Matrix room.
