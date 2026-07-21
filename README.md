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
line (`Host: ...`), then a `From`/`To`/`Subject` header block, then the text body
— and posted to the room.

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
    environment:
      - MATRIX_HOST_LABEL=${HOSTNAME}
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
logfile /var/log/msmtp.log

account matrix-to-smtp
host 127.0.0.1
port 25

account default : matrix-to-smtp
EOF
```


Update permissions

```bash
chmod 644 /etc/msmtprc  # Users need read permissions in order to send mails
touch /var/log/msmtp.log
chmod 666 /var/log/msmtp.log # As all users can execute the sendmail binary, they need to be able to write into /var/log/msmtp.log 
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
