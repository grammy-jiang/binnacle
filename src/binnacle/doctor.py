"""Deployment health checks behind ``binnacle doctor``.

Checks follow the request path: configuration/roots, token, managed services and
their live processes/environments, local MCP authentication, boot/linger,
durable jobs, and recent journal failures. The ChatGPT tunnel and uplink watchdog
keep their own companion doctors. Each check returns a plain ``Check`` record so
the CLI only renders and tests can fake systemctl, procfs, HTTP, and journal IO.

``fail`` breaks a tool/connection and exits 1; ``warn`` is degraded but working;
``ok`` carries the measured value.
"""

import os
import re
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from binnacle import doctor_common as _doctor_common
from binnacle import doctor_jobs as _doctor_jobs
from binnacle import logstats, units
from binnacle.config import CONFIG_FILE_ENV, DEFAULT_CONFIG_FILE, get_settings
from binnacle.deployment_platform import (
    create_linux_provisioner,
    create_service_inspector,
)
from binnacle.doctor_common import Check, fail, ok, warn
from binnacle.doctor_connectivity import _tail_lines, check_endpoint
from binnacle.doctor_provenance import check_provenance
from binnacle.doctor_render import render, render_json
from binnacle.job_manager_doctor import check_job_manager
from binnacle.provenance import runtime_provenance
from binnacle.service_lifecycle_contracts import ManagedServiceInspector
from binnacle.service_log_contracts import ServiceLogError

Systemctl = _doctor_common.Systemctl
systemctl = _doctor_common.systemctl
unit_state = _doctor_common.unit_state

__all__ = [
    "Systemctl",
    "_job_state_safe",
    "_tail_lines",
    "render",
    "render_json",
    "server_busy_reasons",
    "systemctl",
    "unit_state",
]


def _job_state_safe(job_id: str) -> dict | None:
    return _doctor_jobs._job_state_safe(job_id)


def server_busy_reasons(
    unit: str,
    jobs_dir: Path,
    window: str = "-30s",
    fetch: Callable[[str, str], str] = lambda u, s: logstats.fetch_journal(u, s),
    *,
    include_jobs: bool = True,
) -> list[str]:
    return _doctor_jobs.server_busy_reasons(
        unit,
        jobs_dir,
        window,
        fetch,
        include_jobs=include_jobs,
        state_reader=_job_state_safe,
    )


# -- systemd helpers ---------------------------------------------------------


def linger_enabled() -> bool | None:
    """True/False from loginctl; None when loginctl is unavailable."""
    return create_linux_provisioner().inspect_persistence().enabled


# -- checks ------------------------------------------------------------------


def check_config() -> list[Check]:
    out: list[Check] = []
    cfg = Path(os.environ.get(CONFIG_FILE_ENV, DEFAULT_CONFIG_FILE))
    try:
        s = get_settings()
    except Exception as e:  # noqa: BLE001 -- ValidationError, TOML syntax, SettingsError
        return [fail("config", f"settings failed to load: {e}", f"fix {cfg}")]
    source = f"from {cfg}" if cfg.exists() else "defaults (no config file)"
    out.append(ok("config", f"settings loaded {source}"))
    for root in s.roots.allowed:
        if root.is_dir():
            out.append(ok("config", f"root {root} exists"))
        else:
            out.append(
                warn(
                    "config",
                    f"root {root} is not a directory",
                    "create it, or drop it from roots in the config",
                )
            )
    return out


def check_token(token_file: Path) -> list[Check]:
    if not token_file.exists():
        return [fail("token", f"missing at {token_file}", "run `binnacle setup`")]
    out = [ok("token", f"present at {token_file}")]
    mode = token_file.stat().st_mode & 0o777
    if mode == 0o600:
        out.append(ok("token", "file mode is 0600"))
    else:
        out.append(fail("token", f"file mode is {mode:04o}", f"chmod 600 {token_file}"))
    text = token_file.read_text(encoding="utf-8").strip()
    body = text[len("Bearer") :].strip() if text.startswith("Bearer") else text
    if not body:
        out.append(fail("token", "file is empty", "run `binnacle token rotate`"))
    elif not text.startswith("Bearer "):
        out.append(
            warn(
                "token",
                "file lacks the 'Bearer ' prefix",
                "the tunnel sends the file verbatim as the Authorization header; "
                "the server accepts both forms, the tunnel needs the prefix",
            )
        )
    else:
        out.append(ok("token", "file carries the 'Bearer ' prefix"))
    return out


def check_units(
    unit: str,
    inspector: ManagedServiceInspector | None = None,
    waits_for_ready: Callable[[str], bool] = units.unit_waits_for_ready,
    linger: Callable[[], bool | None] = linger_enabled,
) -> tuple[list[Check], str | None]:
    """Returns the checks and the server unit's name when it is active."""
    services = inspector or create_service_inspector()
    status = services.status(unit)
    state = status.state
    out: list[Check] = []
    if state != "active":
        out.append(
            fail(
                "units",
                f"{unit} is {state}",
                f"systemctl --user start {unit}, or `binnacle setup` if it is missing",
            )
        )
        return out, None
    out.append(ok("units", f"{unit} active"))
    restarts = status.restart_count
    if restarts is not None and restarts > 0:
        out.append(
            warn(
                "units",
                f"{unit} restarted {restarts} time(s) since it was started",
                f"journalctl --user -u {unit} for the crash reason",
            )
        )
    else:
        out.append(ok("units", f"{unit} has not crash-restarted"))
    if waits_for_ready(unit):
        out.append(ok("units", f"{unit} waits for its port before reporting started"))
    else:
        out.append(
            warn(
                "units",
                f"{unit} reports started before it listens",
                "add an ExecStartPost port wait (see `binnacle setup` templates); "
                "without it the tunnel probes a dead port on every restart",
            )
        )
    lg = linger()
    if lg is True:
        out.append(ok("units", "linger enabled (services survive logout)"))
    elif lg is False:
        out.append(warn("units", "linger disabled", "loginctl enable-linger"))
    return out, unit


def check_service_env(
    unit: str,
    rg_bin: str,
    user_bin: Path,
    inspector: ManagedServiceInspector | None = None,
) -> list[Check]:
    services = inspector or create_service_inspector()
    status = services.status(unit)
    pid = status.main_pid
    if pid is None:
        return [warn("service-env", f"{unit} has no main PID to inspect")]
    path = services.main_process_path(unit)
    if path is None:
        return [warn("service-env", f"cannot read /proc/{pid}/environ")]
    out: list[Check] = []
    if str(user_bin) in path.split(os.pathsep):
        out.append(ok("service-env", f"{user_bin} is on the service PATH"))
    else:
        out.append(
            fail(
                "service-env",
                f"{user_bin} is not on the service PATH ({path})",
                "add PATH=$HOME/.local/bin:$PATH to ~/.config/environment.d/50-path.conf, "
                "then `systemctl --user daemon-reload` and restart the services; "
                "until then run_command cannot find uv or other user-installed tools",
            )
        )
    for name, tool in (("bash", "run_command"), (rg_bin, "list_files/search_text")):
        found = shutil.which(name, path=path)
        if found:
            out.append(ok("service-env", f"{name} resolves to {found}"))
        else:
            out.append(
                fail(
                    "service-env",
                    f"{name} not found on the service PATH; {tool} will fail",
                    f"install {name} or fix the service PATH",
                )
            )
    return out


def check_boot(
    run: Callable[..., object] | None = None,
    user: str | None = None,
) -> list[Check]:
    """User services only start at boot without a login when lingering is
    on; without it every binnacle unit waits for someone to log in."""
    who = user or os.environ.get("USER") or ""
    runner = None
    if run is not None:
        runner = lambda argv, **kwargs: run(*argv, **kwargs)
    inspection = create_linux_provisioner(run=runner).inspect_persistence(
        user=who, timeout=15
    )
    if inspection.error is not None:
        return [warn("boot", f"loginctl could not run: {inspection.error}")]
    if inspection.enabled:
        return [ok("boot", f"lingering is on for {who}: the units start at boot")]
    return [
        fail(
            "boot",
            f"lingering is off for {who}: after a reboot nothing starts until a login",
            f"loginctl enable-linger {who}",
        )
    ]


def check_jobs(jobs_dir: Path) -> list[Check]:
    if not jobs_dir.is_dir():
        return [ok("jobs", f"spool {jobs_dir} not created yet (no job has run)")]
    if not os.access(jobs_dir, os.W_OK | os.X_OK):
        return [
            fail("jobs", f"spool {jobs_dir} is not writable", "run_command will fail")
        ]
    states = [
        s
        for d in jobs_dir.iterdir()
        if d.is_dir() and (s := _job_state_safe(d.name)) is not None
    ]
    running = sum(1 for s in states if s["state"] == "running")
    unknown = sum(1 for s in states if s["state"] == "unknown")
    out = [
        ok(
            "jobs",
            f"spool {jobs_dir} writable; {len(states)} job(s), "
            f"{running} running, {unknown} orphaned",
        )
    ]
    if unknown:
        out.append(
            warn(
                "jobs",
                f"{unknown} job(s) lost their exit status (server stopped mid-run)",
                "harmless; they age out of the spool",
            )
        )
    return out


_JOURNAL_ERROR = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2}T\S+\s+)?(?:ERROR|CRITICAL):(?:\s|$)|^(?:\[[^]]+\]\s+)?\s*(?:ERROR|CRITICAL)\s+event="
)


def check_journal(
    unit: str,
    since: str,
    fetch: Callable[[str, str], str] = lambda u, s: logstats.fetch_journal(u, s),
) -> list[Check]:
    try:
        text = fetch(unit, since)
    except ServiceLogError as e:
        return [warn("journal", f"journal unavailable: {e}")]
    errors = sum(1 for line in text.splitlines() if _JOURNAL_ERROR.match(line))
    tracebacks = sum(1 for line in text.splitlines() if line.startswith("Traceback"))
    if not errors and not tracebacks:
        return [ok("journal", f"no errors in the {unit} journal since {since}")]
    return [
        warn(
            "journal",
            f"{errors} error line(s) and {tracebacks} traceback(s) since {since}",
            f"journalctl --user -u {unit} --since='{since}' --no-pager -o cat",
        )
    ]


# -- aggregate ---------------------------------------------------------------


@dataclass(slots=True)
class Deployment:
    """Names the doctor needs; the CLI fills these from its constants.
    `unit_path` and `render_unit` let it re-render the server unit from the
    parameters its marker line records and report drift."""

    server_unit: str
    token_file: Path
    server_url: str
    user_bin: Path
    unit_path: Path | None = None
    render_unit: Callable[[Mapping[str, str]], str] | None = None
    jobs_unit: str | None = None
    jobs_unit_path: Path | None = None
    render_jobs_unit: Callable[[Mapping[str, str]], str] | None = None
    jobs_socket: Path | None = None


def run_all(dep: Deployment, since: str = "-1 hour", probe: bool = True) -> list[Check]:
    """Every check, in the order a request travels.

    `probe` is a compatibility selector with no effect on core checks.
    Layered uplink probes belong to `binnacle-watchdog doctor`.
    """
    s = get_settings()
    provenance = runtime_provenance()
    services = create_service_inspector()
    checks: list[Check] = []
    checks += check_provenance(provenance)
    checks += check_config()
    checks += check_token(dep.token_file)
    unit_checks, active = check_units(dep.server_unit, inspector=services)
    checks += unit_checks
    if dep.unit_path is not None and dep.render_unit is not None:
        checks += units.check_unit_drift(
            dep.unit_path,
            "binnacle",
            dep.render_unit,
            "units",
            "binnacle setup [--dev <repo>]",
        )
    if active:
        checks += units.check_unit_process(
            dep.server_unit,
            "units",
            "binnacle setup [--dev <repo>]",
            "binnacle mode dev|prod (restarts at a quiet moment)",
        )
        checks += check_service_env(active, s.rg_bin, dep.user_bin, inspector=services)

    jobs_active: str | None = None
    if dep.jobs_unit is not None and dep.jobs_socket is not None:
        manager_checks, jobs_active = check_job_manager(
            dep.jobs_unit,
            dep.jobs_socket,
            inspector=services,
            expected_revision=provenance.revision,
        )
        checks += manager_checks
        if dep.jobs_unit_path is not None and dep.render_jobs_unit is not None:
            checks += units.check_unit_drift(
                dep.jobs_unit_path,
                "binnacle",
                dep.render_jobs_unit,
                "jobs-service",
                "binnacle setup",
            )
        if jobs_active:
            checks += units.check_unit_process(
                jobs_active,
                "jobs-service",
                "binnacle setup",
                "restart binnacle-jobs.service only when no jobs are running",
            )
            checks += check_service_env(
                jobs_active, s.rg_bin, dep.user_bin, inspector=services
            )
    checks += check_endpoint(dep.server_url, dep.token_file)
    checks += check_boot()
    checks += check_jobs(s.jobs.dir)
    if active:
        checks += check_journal(active, since)
    if jobs_active:
        checks += check_journal(jobs_active, since)
    return checks
