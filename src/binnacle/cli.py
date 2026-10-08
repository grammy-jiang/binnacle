"""binnacle command line -- serve, setup, mode, doctor, stats, token.

The server itself lives in binnacle.server; this module only wires it to
subcommands and provisions the deployment pieces that are ours to manage:
the token and Binnacle's systemd user units. `binnacle-mcp.service` is the
restartable MCP control plane; `binnacle-jobs.service` is the stable command
owner. Development runs the MCP checkout with auto-reload while production
runs installed `binnacle serve`; the job owner never auto-reloads. The ChatGPT
tunnel is the `binnacle-tunnel` companion's business; core keeps only its
unit name, for `token rotate`.
"""

import secrets
import subprocess
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Annotated, Literal

import cyclopts

from binnacle import doctor_jobs, units
from binnacle.config import get_settings
from binnacle.job_manager_unit import JOBS_UNIT, render_job_manager_unit
from binnacle.platform.deployment_platform import (
    create_linux_provisioner,
    create_service_controller,
    create_service_inspector,
)
from binnacle.platform.linux.service_provisioning_linux import (
    LinuxServiceProvisioner,
    PlannedUnit,
)
from binnacle.server_unit import SERVER_UNIT, render_server_unit

app = cyclopts.App(
    name="binnacle",
    help="MCP server that lets AI agents work on a Raspberry Pi.",
)

TOKEN_FILE = get_settings().auth.token_file
UNIT_DIR = units.UNIT_DIR
#: Restarted by `token rotate` when active; owned by the binnacle-tunnel companion.
TUNNEL_UNIT = "binnacle-tunnel.service"
#: Copies of unit files taken before `setup` or `mode` rewrites them.
BACKUP_DIR = get_settings().jobs.dir.parent / "unit-backups"
MODES = ("dev", "prod")


def _write_token(path: Path | None = None) -> None:
    """Write a fresh bearer token as the tunnel and server expect it.

    The tunnel forwards the file verbatim as the Authorization header, so
    the value must carry the ``Bearer `` scheme prefix; the server strips
    it before matching. Mode 0600, trailing newline for editors. The
    default is resolved at call time so tests can repoint TOKEN_FILE.
    """
    path = TOKEN_FILE if path is None else path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"Bearer {secrets.token_urlsafe(32)}\n", encoding="utf-8")
    path.chmod(0o600)


def _provisioner() -> LinuxServiceProvisioner:
    return create_linux_provisioner(unit_dir=UNIT_DIR, backup_dir=BACKUP_DIR)


def _systemctl(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return _provisioner().systemctl(*args, check=check)


def _unit_state(unit: str) -> str:
    return create_service_inspector().status(unit).state


@app.command
def serve(
    host: str = get_settings().serve.host,
    port: int = get_settings().serve.port,
    reload: bool = False,
) -> None:
    """Run the MCP server in the foreground (what the systemd unit runs)."""
    import uvicorn

    # Explicit, not "auto": startup fails loudly if the uvicorn[standard]
    # performance stack (uvloop event loop, httptools parser) is missing,
    # instead of silently degrading to the stdlib implementations.
    uvicorn.run(
        "binnacle.server:app",
        host=host,
        port=port,
        reload=reload,
        loop="uvloop",
        http="httptools",
    )


def _setup_unit_plans(
    mode: str,
    dev: Path | None,
    port: int,
    adopt: bool,
    provisioner: LinuxServiceProvisioner,
) -> tuple[list[PlannedUnit], dict[str, units.WritePlan]]:
    try:
        unit_plans = provisioner.plan_server_jobs(
            mode,
            dev,
            get_settings().serve.host,
            port,
            adopt=adopt,
        )
    except units.UnitError as exc:
        print(exc)
        raise SystemExit(1) from None

    planned: dict[str, units.WritePlan] = {}
    for item in unit_plans:
        plan = item.write
        planned[item.name] = plan
        if plan.diff:
            print(plan.diff + "\n")
        if plan.action == "refuse":
            print(plan.reason)
            raise SystemExit(1)
    return unit_plans, planned


def _apply_setup_units(
    unit_plans: list[PlannedUnit],
    planned: dict[str, units.WritePlan],
    mode: str,
    provisioner: LinuxServiceProvisioner,
    act: Callable[[str, Callable[[], object]], None],
    actions: list[str],
) -> None:
    for item in unit_plans:
        plan = planned[item.name]
        if plan.action == "unchanged":
            actions.append(f"keep {item.path} (already what setup writes, {mode} mode)")
            continue
        verb = "write" if plan.action == "create" else "rewrite"
        description = f"{verb} {item.path} ({mode} mode)"
        if plan.action == "rewrite":
            description = (
                f"{verb} {item.path} ({mode} mode; a copy of the old file goes to "
                f"{provisioner.backup_dir})"
            )
        act(description, partial(provisioner.write_unit, item))


def _print_setup_restart_hints(planned: dict[str, units.WritePlan], mode: str) -> None:
    jobs_plan = planned[JOBS_UNIT]
    if jobs_plan.action == "rewrite" and _unit_state(JOBS_UNIT) == "active":
        print(
            f"{JOBS_UNIT} is running the previous unit/code; leave it running while "
            "jobs are active and restart it at a quiet moment."
        )
    server_plan = planned[SERVER_UNIT]
    if server_plan.action == "rewrite" and _unit_state(SERVER_UNIT) == "active":
        print(
            f"{SERVER_UNIT} is running on the previous unit file; restart it at "
            f"a quiet moment: `binnacle mode {mode}`"
        )


@app.command
def setup(
    dev: Path | None = None,
    port: int = get_settings().serve.port,
    dry_run: bool = False,
    adopt: bool = False,
) -> None:
    """Provision the server side: token, MCP unit, and stable jobs unit.

    Parameters
    ----------
    dev
        Path to a binnacle git checkout: the unit runs it with auto-reload
        (development mode). Without it the unit runs the installed
        `binnacle serve` (production mode).
    port
        Local port the server binds; the tunnel forwards to it.
    dry_run
        Print every action, and the unit diff, instead of performing them.
    adopt
        Take over a unit file no binnacle setup command wrote (a hand-written
        one), after reviewing the diff `--dry-run` shows. It is backed up
        first.
    """
    actions: list[str] = []

    def act(description: str, fn: Callable[[], object]) -> None:
        actions.append(description)
        if not dry_run:
            fn()

    if not TOKEN_FILE.exists():
        act(f"generate bearer token at {TOKEN_FILE} (mode 0600)", _write_token)
    else:
        actions.append(f"keep existing token at {TOKEN_FILE}")

    mode = "dev" if dev is not None else "prod"
    provisioner = _provisioner()
    unit_plans, planned = _setup_unit_plans(mode, dev, port, adopt, provisioner)
    _apply_setup_units(unit_plans, planned, mode, provisioner, act, actions)

    act("systemctl --user daemon-reload", provisioner.reload_definitions)
    act(
        f"systemctl --user enable --now {JOBS_UNIT}",
        lambda: provisioner.enable_now(JOBS_UNIT),
    )
    act(
        f"systemctl --user enable --now {SERVER_UNIT}",
        lambda: provisioner.enable_now(SERVER_UNIT),
    )
    act(
        "loginctl enable-linger (services survive logout and reboot)",
        provisioner.enable_persistence,
    )

    prefix = "would " if dry_run else ""
    for action in actions:
        print(f"{prefix}{action}")
    if dry_run:
        print("\ndry run: nothing was changed.")
        return
    print("\nserver side is configured. For ChatGPT, the tunnel is a separate")
    print("companion: `binnacle-tunnel setup` once its profile is written.")
    _print_setup_restart_hints(planned, mode)


def _current_marker(
    provisioner: LinuxServiceProvisioner | None = None,
) -> units.Marker | None:
    return (provisioner or _provisioner()).current_marker(SERVER_UNIT)


@app.command
def mode(
    target: Literal["dev", "prod", "status"] = "status",
    repo: Path | None = None,
    force: bool = False,
) -> None:
    """Switch the unit between development (checkout + reload) and
    production (installed, no reload), then restart it at a quiet moment.

    The unit keeps its name, so the tunnel, the journal readers and the
    watchdog need no change and the mode survives a reboot. `status`
    reports the mode the unit's marker line records and the unit's state.
    `repo` is needed for `dev` only when the unit has never been in
    development mode. With durable manager ownership, background commands
    do not block an MCP restart; recent tool calls still do. If the local
    rollback setting explicitly selects the embedded owner, running jobs
    remain blockers because they share the MCP cgroup. `--force` overrides.
    """
    provisioner = _provisioner()
    marker = _current_marker(provisioner)
    if target == "status":
        state = _unit_state(SERVER_UNIT)
        if marker is None:
            print(f"{SERVER_UNIT}: {state}; not managed by `binnacle setup`")
        elif marker.legacy:
            print(f"{SERVER_UNIT}: {state}; pre-2026-09-20 marker, mode unknown")
        else:
            shown = ", ".join(f"{k}={v}" for k, v in marker.params.items())
            print(
                f"{SERVER_UNIT}: {state}; {marker.params.get('mode', '?')} mode ({shown})"
            )
        return
    if marker is None or marker.legacy:
        print(
            f"{SERVER_UNIT} is not managed by `binnacle setup` (no marker with "
            "parameters); run `binnacle setup [--dev <repo>] --adopt` first"
        )
        raise SystemExit(1)
    known = marker.params
    if known.get("jobs_owner") != "manager":
        print(
            f"{SERVER_UNIT} predates durable job ownership; run `binnacle setup "
            "[--dev <repo>]` before switching mode"
        )
        raise SystemExit(1)
    checkout = repo or (Path(known["repo"]) if "repo" in known else None)
    if target == "dev" and checkout is None:
        print("development mode needs the checkout: `binnacle mode dev --repo <path>`")
        raise SystemExit(1)
    try:
        port = int(known.get("port") or get_settings().serve.port)
        item = provisioner.plan_server(
            target,
            checkout,
            known.get("host") or get_settings().serve.host,
            port,
        )
    except units.UnitError as e:
        print(e)
        raise SystemExit(1) from None
    plan = item.write
    if plan.action == "refuse":
        print(plan.reason)
        raise SystemExit(1)
    if not force:
        from binnacle import doctor as checks

        job_settings = get_settings().jobs
        include_jobs = (
            job_settings.owner == "embedded"
            or not doctor_jobs.server_uses_manager(
                SERVER_UNIT, inspector=create_service_inspector()
            )
        )
        busy = checks.server_busy_reasons(
            SERVER_UNIT, job_settings.dir, include_jobs=include_jobs
        )
        if busy:
            print("not a quiet moment for a restart:")
            for reason in busy:
                print(f"  {reason}")
            print("retry later, or pass --force")
            raise SystemExit(1)
    if plan.action == "rewrite":
        if plan.diff:
            print(plan.diff + "\n")
        provisioner.write_unit(item)
        provisioner.reload_definitions()
    action = create_service_controller().restart(SERVER_UNIT, timeout=None)
    if action.returncode != 0:
        detail = (
            action.stderr.strip() or action.launch_error or f"exit {action.returncode}"
        )
        print(f"failed to restart {SERVER_UNIT}: {detail}")
        raise SystemExit(1)
    print(f"{target} mode: {SERVER_UNIT} restarted and {_unit_state(SERVER_UNIT)}.")


@app.command
def doctor(
    since: str = "-1 hour",
    as_json: Annotated[bool, cyclopts.Parameter(name="--json")] = False,
    probe: bool = True,
) -> None:
    """Check the deployment end to end and exit 1 on any FAIL.

    Checks: config and roots, token file, the systemd unit (active, the
    file `setup` writes, the process it started, no crash restarts,
    linger), the running server's PATH (~/.local/bin, ripgrep, bash),
    /mcp auth with and without the token, the job spool, and recent journal errors. The ChatGPT tunnel
    and its poller are `binnacle-tunnel doctor`'s, the uplink watchdog is
    `binnacle-watchdog doctor`'s. WARN lines are degraded but working and
    do not change the exit code.

    Parameters
    ----------
    since
        journalctl window for the error scan (--since="-2 hours").
    as_json
        Emit the checks as JSON instead of the text report.
    probe
        Compatibility selector; --probe and --no-probe have no effect on core
        checks. Use binnacle-watchdog doctor for layered uplink probes.
    """
    from binnacle import doctor as checks

    serve_cfg = get_settings().serve
    provisioner = _provisioner()
    dep = checks.Deployment(
        server_unit=SERVER_UNIT,
        unit_path=provisioner.unit_path(SERVER_UNIT),
        render_unit=render_server_unit,
        jobs_unit=JOBS_UNIT,
        jobs_unit_path=provisioner.unit_path(JOBS_UNIT),
        render_jobs_unit=render_job_manager_unit,
        jobs_socket=get_settings().jobs.socket_path,
        token_file=TOKEN_FILE,
        server_url=f"http://{serve_cfg.host}:{serve_cfg.port}/mcp",
        user_bin=Path.home() / ".local" / "bin",
    )
    results = checks.run_all(dep, since=since, probe=probe)
    text, code = (checks.render_json if as_json else checks.render)(results)
    print(text)
    raise SystemExit(code)


@app.command
def stats(
    since: str = "-24 hours",
    until: str | None = None,
    unit: str = "binnacle-mcp",
    system_resources: Annotated[
        bool, cyclopts.Parameter(name="--system-resources")
    ] = False,
) -> None:
    """Usage statistics from the server journal.

    Parameters
    ----------
    since
        journalctl time spec. A value starting with a dash needs the
        equals form (--since="-2 days"); "2 days ago" needs no dash.
    until
        Optional end of the window, same syntax.
    unit
        Systemd user unit whose journal to analyze.
    system_resources
        Also read Webmin system-status history for the same time window.
    """
    from binnacle import logstats

    journal_units: str | tuple[str, str] = unit
    if unit in {"binnacle-mcp", SERVER_UNIT}:
        journal_units = (unit, JOBS_UNIT)
    from binnacle.platform.contracts.service_log_contracts import ServiceLogError

    try:
        raw_journal = logstats.fetch_journal(journal_units, since, until)
    except ServiceLogError as exc:
        raise SystemExit(str(exc)) from None
    records, startups = logstats.parse(raw_journal)
    shown_units = ",".join(journal_units) if isinstance(journal_units, tuple) else unit
    print(
        f"binnacle stats -- unit {shown_units}, since {since}"
        + (f", until {until}" if until else "")
    )
    analysis = logstats.analyze(records, startups)
    print(logstats.render(analysis))
    if system_resources:
        from binnacle.observability.system_resource_history import (
            create_system_resource_history,
        )

        print("\n" + create_system_resource_history().render_window(since, until))


token_app = cyclopts.App(name="token", help="Bearer token operations.")
app.command(token_app)


@token_app.command
def rotate() -> None:
    """Write a new token and restart the server and tunnel services.

    The tunnel caches the token at startup and re-registers its poller with
    OpenAI. Its unit (the binnacle-tunnel companion's) holds the restart
    until the new instance answers /readyz and reports its MCP probe ok, so
    a `chatgpt-refresh` right after this call has a chance.
    """
    _write_token()
    print(f"wrote new token to {TOKEN_FILE}")
    controller = create_service_controller()
    failed = False
    for unit in (SERVER_UNIT, TUNNEL_UNIT):
        if _unit_state(unit) != "active":
            continue
        action = controller.restart(unit, timeout=None)
        if action.returncode == 0:
            print(f"restarted {unit}")
            continue
        failed = True
        detail = (
            action.stderr.strip() or action.launch_error or f"exit {action.returncode}"
        )
        print(f"failed to restart {unit}: {detail}")
    if failed:
        raise SystemExit(1)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
