# Start-up imports: fail fast (E1, E1-a4)

A serving process (the MCP server or a job manager) imports every binnacle
module it can use at start (`binnacle.startup_imports`), so it never
first-imports source that a later deploy synced into the shared checkout.

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

`at` is the raising (innermost) frame, relative to the binnacle package root
or to its site-packages root for a third-party frame. The exception message
and the traceback are never logged (a message can carry a secret or a path to
one).

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
| MCP server (the `uvicorn binnacle.server:app` process) | in `server.py`, via `on_failure` | `START_CONFIRM_S` (1 s) after the ASGI lifespan startup, if the process is still alive: uvicorn binds right after the lifespan and exits on a bind error |
| Linux manager `main()` | via `on_failure` | after the jobs socket is bound and announced (`serve_forever`) |
| Darwin manager `main()` | in the `except StartupImportFailed` handler | once the endpoint this process published appears (the `.auth` file carries this pid and lease generation) |

A start that fails after the import phase but before the bind or publish (a
bad socket path, a lock or config error, a port in use) keeps the record.
`python -m binnacle.server` and `fastmcp` runs are not the serving entry: they
neither write nor clear it (the failure is still the single log line and
exit 70).

Location: `<state root>/startup-import/<process>.json` (directory mode 0700),
where the state root is the parent of the instance's configured `jobs.dir`
(default `~/.local/state/binnacle`). `binnacle.startup_imports` has no HOME or
`XDG_STATE_HOME` default; the entry point passes the resolved root and
`doctor` resolves it the same way. Fields: `process`, UTC `time`, `revision`,
`module`, `error_class`, `where` (raising file:line). Never the exception
message.

`binnacle doctor` reports every record as `startup` with its age and
revision. A record whose revision equals the running checkout's is a FAIL
(exit 1). A record of an older revision is `STALE` (WARN): it predates the
current revision's start and a clean start clears it. `startup ok` when none
exists. Under systemd `Restart=` or launchd `KeepAlive` a failing process
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
