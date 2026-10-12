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

Before it exits, the failing process writes
`$XDG_STATE_HOME/binnacle/startup-import/<process>.json` (default
`~/.local/state/binnacle/startup-import/`, directory mode 0700): process, pid,
module, error class, raising frame, UTC time and exit code. A clean start of
that process removes its record.

`binnacle doctor` reports each record as a `startup` FAIL (exit 1), and
`startup ok` when none exists. Under systemd `Restart=` or launchd `KeepAlive`
a failing process crash-loops; the record keeps the cause visible on every
restart, and the deploy smoke (`scripts/deploy_smoke.py`) treats the failing
doctor as an ALERT, so a gated deploy rolls back.
