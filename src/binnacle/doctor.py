"""Deployment health checks behind ``binnacle doctor``.

Checks follow the request path: configuration/roots, token, managed services and
their live processes/environments, local MCP authentication, uplink, boot/linger,
durable jobs, and recent journal failures. The ChatGPT tunnel and uplink watchdog
keep their own companion doctors. Each check returns a plain ``Check`` record so
the CLI only renders and tests can fake systemctl, procfs, HTTP, and journal IO.

``fail`` breaks a tool/connection and exits 1; ``warn`` is degraded but working;
``ok`` carries the measured value.
"""

import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

from binnacle import doctor_jobs as _doctor_jobs
from binnacle import logstats, units
from binnacle.config import CONFIG_FILE_ENV, DEFAULT_CONFIG_FILE, get_settings
from binnacle.doctor_common import (
    Check,
    Systemctl,
    fail,
    ok,
    systemctl,
    unit_property,
    unit_state,
    warn,
)
from binnacle.doctor_connectivity import _tail_lines, check_endpoint, check_uplink
from binnacle.job_manager_doctor import check_job_manager

__all__ = ["_job_state_safe", "_tail_lines", "server_busy_reasons"]


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
    proc = subprocess.run(
        [
            "loginctl",
            "show-user",
            os.environ.get("USER", ""),
            "-p",
            "Linger",
            "--value",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() == "yes"


def process_environ(pid: int) -> dict[str, str] | None:
    try:
        raw = Path(f"/proc/{pid}/environ").read_bytes()
    except OSError:
        return None
    env: dict[str, str] = {}
    for item in raw.split(b"\0"):
        if b"=" in item:
            k, _, v = item.partition(b"=")
            env[k.decode(errors="replace")] = v.decode(errors="replace")
    return env


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
    run: Systemctl = systemctl,
    linger: Callable[[], bool | None] = linger_enabled,
) -> tuple[list[Check], str | None]:
    """Returns the checks and the server unit's name when it is active."""
    state = unit_state(unit, run)
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
    restarts = unit_property(unit, "NRestarts", run)
    if restarts.isdigit() and int(restarts) > 0:
        out.append(
            warn(
                "units",
                f"{unit} restarted {restarts} time(s) since it was started",
                f"journalctl --user -u {unit} for the crash reason",
            )
        )
    else:
        out.append(ok("units", f"{unit} has not crash-restarted"))
    if unit_property(unit, "ExecStartPost", run):
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
    run: Systemctl = systemctl,
    environ: Callable[[int], dict[str, str] | None] = process_environ,
) -> list[Check]:
    pid_text = unit_property(unit, "MainPID", run)
    if not pid_text.isdigit() or int(pid_text) == 0:
        return [warn("service-env", f"{unit} has no main PID to inspect")]
    env = environ(int(pid_text))
    if env is None:
        return [warn("service-env", f"cannot read /proc/{pid_text}/environ")]
    path = env.get("PATH", "")
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
    run: Callable[..., "subprocess.CompletedProcess[str]"] | None = None,
    user: str | None = None,
) -> list[Check]:
    """User services only start at boot without a login when lingering is
    on; without it every binnacle unit waits for someone to log in."""
    runner = run or (
        lambda *a, **k: subprocess.run(
            a, capture_output=True, text=True, check=False, timeout=15
        )
    )
    who = user or os.environ.get("USER") or ""
    try:
        proc = runner("loginctl", "show-user", who, "-p", "Linger")
    except (OSError, subprocess.TimeoutExpired) as e:
        return [warn("boot", f"loginctl could not run: {e}")]
    value = proc.stdout.strip().split("=", 1)[-1] if proc.returncode == 0 else ""
    if value == "yes":
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
    except SystemExit as e:
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

    `probe=False` skips the checks that touch the network, for tests and
    for a quick local-only look.
    """
    s = get_settings()
    checks: list[Check] = []
    checks += check_config()
    checks += check_token(dep.token_file)
    unit_checks, active = check_units(dep.server_unit)
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
        checks += check_service_env(active, s.rg_bin, dep.user_bin)

    jobs_active: str | None = None
    if dep.jobs_unit is not None and dep.jobs_socket is not None:
        manager_checks, jobs_active = check_job_manager(dep.jobs_unit, dep.jobs_socket)
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
            checks += check_service_env(jobs_active, s.rg_bin, dep.user_bin)
    checks += check_endpoint(dep.server_url, dep.token_file)
    # The uplink is the one check here that sees past localhost; the
    # tunnel's poller, the other one, is `binnacle-tunnel doctor`'s.
    if probe:
        checks += check_uplink()
    checks += check_boot()
    checks += check_jobs(s.jobs.dir)
    if active:
        checks += check_journal(active, since)
    if jobs_active:
        checks += check_journal(jobs_active, since)
    return checks


def render(checks: Iterable[Check]) -> tuple[str, int]:
    """Human-readable report and the process exit code (1 on any fail)."""
    label = {"ok": "ok  ", "warn": "WARN", "fail": "FAIL"}
    lines = ["binnacle doctor"]
    counts = {"ok": 0, "warn": 0, "fail": 0}
    for c in checks:
        counts[c.status] += 1
        lines.append(f"  [{label[c.status]}] {c.group}: {c.detail}")
        if c.hint and c.status != "ok":
            lines.append(f"         hint: {c.hint}")
    lines.append(f"{counts['ok']} ok, {counts['warn']} warn, {counts['fail']} fail")
    return "\n".join(lines), 1 if counts["fail"] else 0


def render_json(checks: Iterable[Check]) -> tuple[str, int]:
    items = [asdict(c) for c in checks]
    code = 1 if any(c["status"] == "fail" for c in items) else 0
    return json.dumps({"checks": items, "exit_code": code}, indent=2), code
