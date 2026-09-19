# binnacle

Binnacle is a small MCP server that lets an AI agent work on a Linux/Raspberry Pi
through deterministic tools: read/search files, run commands, and manage
long-running jobs.

> **Status:** proof of concept. This repository is not packaged or deployed as a
> release yet.

## Quick start

Requirements: Linux with systemd user services, `bash`, `ripgrep` (`rg`), and
[uv](https://docs.astral.sh/uv/). Python 3.10-3.14 is supported.

```bash
git clone https://github.com/grammy-jiang/binnacle.git
cd binnacle

uv sync --locked --group dev

# Preview the machine changes first.
uv run binnacle setup --dev "$PWD" --dry-run

# Create the bearer token and systemd user units.
uv run binnacle setup --dev "$PWD"

# For POC/development, run directly from this checkout with auto-reload.
uv run binnacle mode dev

# Verify configuration, auth, service state, jobs and connectivity.
uv run binnacle doctor
```

The local MCP endpoint is:

```text
http://127.0.0.1:8000/mcp
```

The bearer credential is created at:

```text
~/.config/binnacle/token
```

Do not commit or share that file.

## Configuration

Defaults are suitable for a typical development machine:

- default working root: `~/Projects`
- additional allowed root: `/tmp`
- MCP listen address: `127.0.0.1:8000`

Override them in `~/.config/binnacle/config.toml`, for example:

```toml
[roots]
default_root = "/home/your-user/Projects"
extra_roots = ["/tmp"]

[serve]
host = "127.0.0.1"
port = 8000
```

Environment variables use the `BINNACLE_` prefix and `__` for nested values,
for example `BINNACLE_SERVE__PORT=9000`. Set `BINNACLE_CONFIG_FILE` to use a
different TOML file.

## Connect an AI agent

Point any MCP client that supports Streamable HTTP at the endpoint above and use
the token file as its Bearer credential.

For a remote client such as ChatGPT, expose the local MCP endpoint through an
appropriate authenticated tunnel/connector. Binnacle can integrate with a
`tunnel-client` already installed on the machine, but it deliberately does not
install or provision the external tunnel account for you.

An AI agent setting up Binnacle should follow this README, use
`binnacle setup --dry-run` before changing the host, and finish with
`binnacle doctor`.

## Development checks

```bash
uv run pre-commit run --all-files
uv run tox -e coverage-policy
uv run tox
```

GitHub Actions runs tests and code-quality checks only. There is currently no
release, packaging, or deployment pipeline.
