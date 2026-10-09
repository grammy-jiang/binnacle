# binnacle

Binnacle is a small MCP server that lets an AI agent work on a Linux/Raspberry Pi
through deterministic tools: read/search files, run commands, and manage
long-running jobs.

> **Status:** developer-oriented Linux proof of concept. Distribution
> releases are versioned and verified independently of Raspberry Pi
> deployments. Check the package index for PyPI availability.

**Security:** Binnacle allows AI clients to read/write files and run shell
commands within configured roots. The bearer token is sensitive; client
identifiers used for tool visibility are not a strong authorization boundary.
Use it only on a trusted machine/network, keep the endpoint bound to localhost,
and put an authenticated gateway in front of any tunnel. **Do not expose the
MCP endpoint to the public Internet without appropriate security controls.**

## Install from PyPI

Binnacle targets Linux with Python 3.10–3.14. Its managed services use
systemd --user and additionally require bash and ripgrep (rg).

```bash
python -m pip install binnacle-mcp==1.0.1
binnacle --help
binnacle doctor
```

Review any host changes before running setup:

```bash
binnacle setup --dry-run
```

For managed services, configuration, bearer token provisioning and the optional
tunnel companion, follow the Quick start and configuration guidance below.
Installation does **not** automatically start or expose an MCP server.

## Quick start

Requirements: Linux with systemd user services, bash, ripgrep (rg), Git, and
uv. Python 3.10-3.14 is supported by the current test matrix.

```bash
git clone https://github.com/grammy-jiang/binnacle.git
cd binnacle

# Create/sync the development environment, install every configured Git hook,
# and verify the checkout.
uv run scripts/dev.py bootstrap

# Preview the machine changes first: every action, and the unit diff.
uv run binnacle setup --dev "$PWD" --dry-run

# Create the bearer token plus the MCP and durable-jobs systemd user units.
# The MCP checkout auto-reloads in development; the jobs owner stays stable.
# A hand-written unit is refused: review the diff, then add --adopt to take it
# over (the old file is backed up).
uv run binnacle setup --dev "$PWD"

# Later, switch the MCP unit to the installed package without reload, or back.
# The durable jobs service is a sibling and is not restarted by mode.
uv run binnacle mode prod
uv run binnacle mode dev

# Verify package/revision provenance, configuration, auth, both managed
# units/processes, the private jobs socket, durable job state, and connectivity.
uv run binnacle doctor

# ChatGPT only: the OpenAI tunnel unit belongs to its own companion, never to
# binnacle setup; other agents reach the server without it.
uv run binnacle-tunnel setup --dry-run
uv run binnacle-tunnel doctor
```

The local MCP endpoint is [http://127.0.0.1:8000/mcp](http://127.0.0.1:8000/mcp).

The bearer credential is created at ~/.config/binnacle/token. Do not commit or
share that file.

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

## Development

[DEVELOPMENT.md](DEVELOPMENT.md) is the canonical repository-development guide.
Local AI development agents use thin project entry points: Claude Code reads
`CLAUDE.md`, while Codex and other agents that honour the convention read
`AGENTS.md`. Both defer to `DEVELOPMENT.md` for the shared workflow. The normal
environment entry points are:

```bash
uv run scripts/dev.py doctor
uv run scripts/dev.py worktrees
```

The explicit local quality gates are:

```bash
uv run pre-commit run --all-files
uv run pre-commit run --hook-stage pre-push --all-files
uv run tox -e coverage-policy -- --seed 12345
uv run tox
```

GitHub Actions separately enforces code quality, the supported Python
compatibility matrix, the coverage policy, and wheel-artifact packaging. A
scheduled Security workflow audits the locked runtime and development
dependencies daily. Dependabot version updates and repository-side governance
are documented in `docs/github-governance.md`.

GitHub release artifacts are published separately from Raspberry Pi
deployments. PyPI releases use a dedicated GitHub Actions Trusted Publisher
workflow with manual environment approval and no stored PyPI API token.
See docs/release-readiness.md for release controls; production deployment
uses the existing guarded live-smoke flow described in DEVELOPMENT.md.
