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

# Preview the machine changes first: every action, and the unit diff.
uv run binnacle setup --dev "$PWD" --dry-run

# Create the bearer token plus the MCP and durable-jobs systemd user units.
# The MCP checkout auto-reloads in development; the jobs owner stays stable.
# A hand-written unit is refused: review
# the diff, then add --adopt to take it over (the old file is backed up).
uv run binnacle setup --dev "$PWD"

# Later, switch the MCP unit to the installed package without reload, or
# back. The durable jobs service is a sibling and is not restarted by mode.
uv run binnacle mode prod
uv run binnacle mode dev

# Verify configuration, auth, both managed units/processes, the private
# jobs socket, durable job state, and connectivity.
uv run binnacle doctor

# ChatGPT only: the OpenAI tunnel unit belongs to its own companion, never
# to `binnacle setup`; other agents reach the server without it.
uv run binnacle-tunnel setup --dry-run
uv run binnacle-tunnel doctor
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
