# Start-up imports: fail fast (E1, E1-a4)

A serving process (the MCP server or a job manager) imports every binnacle
module it can use at start (`binnacle.startup_imports`), so it never
first-imports source that a later deploy synced into the shared checkout.

## The pinned module sets (SD-90)

The MCP server's REQUIRED set is a **frozen literal**,
`binnacle.startup_server_modules.SERVER_MODULES` (common names plus each OS's
own adapters). The runtime imports exactly those names, in order, and **never
walks the installed package directory**: a stray `.py` there is not imported.
The file is generated, once per change of the module tree, by
`scripts/gen_startup_server_modules.py` (`--write` regenerates it, `--check`
exits 1 on drift, no flag prints it). The generator is the only code that walks
the tree, from the source files and without importing anything, minus the
exclusions pinned in `startup_imports` (`_ALWAYS_EXCLUDED`: the server, the CLI
and the companions; `_EXCLUDED_BY_OS`: the other OS's adapters).
`tests/unit/core/test_r6w3_e1g_server_set.py` fails with
`regenerate with: uv run python scripts/gen_startup_server_modules.py --write`
when the literal differs from that walk, for both OSes from either host. A new,
renamed or removed runtime module therefore needs one regeneration commit.

A job manager imports its own pinned `MANAGER_MODULES` instead (the whole MCP
tree doubled the Darwin manager's RSS, E1B-R1). The G3 architecture scan
(`tests/unit/core/test_platform_architecture.py`, SD-90) allows
`importlib.import_module(name)` only in `startup_imports._required_import` and
proves every target is one of these frozen binnacle constants, never config,
environment or user input.

## OPS-FOLLOWUP-shared-venv-lazy-import

E1 covers `binnacle.*` only. Third-party and standard-library modules that a
process imports lazily still come from the shared virtual environment; the
gated deploy restarts the MCP server whenever `pyproject.toml` or `uv.lock`
changes (RE1-F3).

## Policy: a required import failure aborts start-up

Any `ImportError`, `Exception`, `SystemExit` or other `BaseException`
(except `KeyboardInterrupt`) raised while importing a REQUIRED module, including
a package `__init__` reached by the name walk, aborts start-up:

- the MCP server exits before uvicorn binds the port;
- the Linux job manager (`binnacle-jobs`, `binnacle.features.commands.job_manager`)
  exits before it binds the jobs socket;
- the Darwin job manager (`com.binnacle.jobs`,
  `binnacle.platform.darwin.job_manager_entry`) exits before the service lease
  and the socket.

Each exits with **`EX_STARTUP_IMPORT` = 70** (`EX_SOFTWARE`, sysexits.h),
distinct from the Darwin manager's other codes (1 failed, 64 usage,
75 tempfail/busy, 78 config). It logs exactly one line:

```text
event=startup_import_failed process=<mcp-server|job-manager> module=<name> error_class=<type> at=<file:line> exit=70
```

`at` names where an operator opens the source, never a frozen or importlib
frame: a SyntaxError's own source location. For other exceptions, prefer the
innermost traceback frame inside Binnacle (excluding startup_imports.py
itself) over a nested third-party dependency. A test-owned direct import may
use the requested module's own source outside Binnacle. If no attributable
source exists, report the requested module name and line zero; never name an
unrelated third-party, frozen or stdlib importlib frame. The exception
message and traceback are never logged, as they may contain secrets.

`OPTIONAL_MODULES` is the pinned allowlist of modules that may instead fail,
warn and report themselves unavailable at call time. No such module exists
today; the list is empty and a test pins it.

## Durable record and doctor check

The record is owned by the real entry points, never by an import (E1-a5,
SD-84). Importing `binnacle.server`, or calling `import_runtime_modules` /
`import_manager_modules` in any process (a test, a CLI, a REPL), neither
writes nor clears it.

| Entry point | Writes on a failure | Clears after a successful start |
| --- | --- | --- |
| `binnacle serve` (the Mac `com.binnacle.mcp` entry and the Linux prod-mode unit) | in `server.py`, via `on_failure` | when the public `uvicorn.Server.started` turns True (after the lifespan startup AND the bind) |
| the uvicorn CLI, `uvicorn binnacle.server:app` (the Linux dev unit) | in `server.py`, via `on_failure` | `START_CONFIRM_S` (1 s) after the ASGI lifespan startup, if the process is still alive: uvicorn binds right after the lifespan and exits on a bind error |
| Linux manager `main()` | via `on_failure` | after the jobs socket is bound and announced (`serve_forever`) |
| Darwin manager `main()` | in the `except StartupImportFailed` handler | once the endpoint this process published appears (the `.auth` file carries this pid and lease generation) |

How the MCP server recognises itself. The installed binnacle console entry
starts at binnacle.entrypoint:main: for the serve subcommand it activates
startup_imports.serving_entry() and verifies pinned modules before importing
the main CLI. A failure importing the CLI itself aborts with exit 70 and a
redacted event. Then cli.serve runs uvicorn.run inside its own serving_entry()
scope, active until uvicorn.run returns. server.py then writes
the record on a failed import and, because binnacle owns the uvicorn server
there, wraps `uvicorn.Server.startup` to clear the record once `started` is
True, and only while the explicit serving mark is active and the server's
configured app identifies Binnacle. Another Uvicorn server in the same
interpreter must never clear the Binnacle start-up record. The uvicorn CLI hands binnacle no `Server` object, so it is recognised by
argv (`bin/uvicorn`, `uvicorn/__main__.py`) and keeps the 1 s rule. `binnacle
serve` is never recognised by argv: only the explicit mark counts, so an
unmarked `binnacle ...` importer (and the worker of an ad-hoc
`binnacle serve --reload`, a spawned process that did not enter the mark)
neither writes nor clears the record. Any other importer (pytest, `python -c`,
another `binnacle` subcommand, `python -m binnacle.server`, `fastmcp`) likewise
leaves it alone: `test_r6w3_e1g_serve_entry.py` pins nine argv variants.

**`uvicorn --reload` (the dev unit).** The reload supervisor binds the port
first and the worker imports `binnacle.server` afterwards, so "exits before it
binds" is true of the worker only: the supervisor keeps the port bound (and
refusing) while a worker that exits 70 is restarted on the next file change.
The record is written by the worker (its argv0 is the uvicorn CLI), and the
dev unit's `ExecStartPost` 30 s port probe, `binnacle doctor` and the deploy
smoke are what make this visible. The production-mode unit (`binnacle serve`,
no reload) does exit before the bind.

A start that fails after the import phase but before the bind or publish (a
bad socket path, a lock or config error, a port in use) keeps the record.
A failed import still ends every process with the single log line and exit 70,
whether or not that process owns the record.

Location: `<state root>/startup-import/<process>.json` (directory mode 0700),
where the state root is the parent of the instance's configured `jobs.dir`
(default `~/.local/state/binnacle`). `binnacle.startup_imports` has no HOME or
`XDG_STATE_HOME` default; the entry point passes the resolved root and
`doctor` resolves it the same way. Fields: `process`, UTC `time`, `revision`,
`module`, `error_class`, `where` (raising file:line). Never the exception
message.

`binnacle doctor` reports every record as `startup` with its age and
revision. A record matching the running checkout is a FAIL (exit 1). **Unknown,
empty, installed or otherwise unverified revision identities are also FAIL**:
an import error may precede loading the provenance module, and cannot be
assumed to belong to a prior release. Only a record carrying a valid Git
revision different from the current valid revision is `STALE` (WARN).
A clean start clears the record; `startup ok` requires that none exists. Under systemd `Restart=` or launchd `KeepAlive` a failing process
crash-loops; the record keeps the cause visible on every restart, and the
deploy smoke (`scripts/deploy_smoke.py`) treats the failing doctor as an
ALERT, so a gated deploy rolls back.

## Test hygiene

`tests/conftest.py` points `XDG_STATE_HOME` at a scratch directory for the
whole session, makes any in-process path to the real
`~/.local/state/binnacle/startup-import` raise, and compares that directory
before and after the session (a child process cannot be patched). It does not
snapshot the rest of `~/.local/state/binnacle`: production jobs state there
changes legitimately while a suite runs.

### Earliest process-entry import boundary (R6W3-01)

The CLI entrypoint and Linux binnacle-jobs console entry must not import
business modules before the pinned startup check. Manual Python module
entrypoints on Linux and Darwin guard before service/backends load;
ordinary library imports remain inert. The server guards required imports
before importing its FastMCP adapters and tool factories.

At process entry, the configured state root is resolved ONCE, inside an
import-failure boundary, before the rest of the pinned REQUIRED modules are
loaded. Linux uses its normal Settings; Darwin's manager uses the same
file-only ManagerConfig as the real running service. When the configured
state root is valid, early failures write the structured record at that
saved root. The failure callback NEVER rebuilds settings or follows an
unverified environment override. If config itself cannot initialize there
is no trustworthy state root: exit 70 and the redacted log remain mandatory,
with an explicit log-only record error instead of a guessed HOME/XDG path.

The required provenance module is not imported by startup_imports on its
own; it is loaded inside the protected pinned module set. If provenance
cannot initialize, the failure record uses revision unknown rather than
re-importing it while reporting an existing fault. Import-time SystemExit
in the serve CLI is converted to exit 70 and does not leak its message.
Do not restore unguarded console targets: binnacle.entrypoint:main and
binnacle.job_manager_cli:main are required.
