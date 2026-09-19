"""Deployment health checks behind `binnacle doctor`.

Every check is a plain function that returns Check records, so the CLI
only renders and the tests only need fakes for the outside world
(systemctl, /proc, HTTP, the journal). Checks cover the whole chain a
request takes, ChatGPT -> tunnel -> server -> tools -> shell, plus the
failure modes seen in production:

- config: settings load, configured roots exist.
- token: present, mode 0600, non-empty, carries the "Bearer " prefix the
  tunnel forwards verbatim.
- units: exactly one server unit active, a port-readiness ExecStartPost, no
  crash-loop restarts, linger.
- service environment: the running server's PATH (read from /proc, not
  from the manager, because a unit started at boot keeps the pre-login
  PATH) holds ~/.local/bin, ripgrep, and bash.
- endpoint: /mcp refuses a request without the token and accepts one
  with it, so a rotated-but-not-restarted token shows up here.
- tunnel: unit active and ordered after the server unit, config points at
  the server URL and at the token file, health endpoint answers.
- uplink: the default route actually carries traffic, probed end to end
  per interface (gateway, DNS, TCP to the upstream host).
- poller: the tunnel's own log shows it reaching OpenAI. This is the only
  check that sees what ChatGPT sees.
- driver: the daily wlan1 USB 3 stability sample (external cron job);
  skipped where that job does not exist.
- jobs: spool directory writable; counts of running and orphaned jobs.
- journal: errors and tracebacks in a recent window.

The last three exist because every check above them is local. On
2026-09-12 a wedged USB radio held the default route for 48 minutes:
units active, endpoint answering, tunnel health port green, `doctor`
all-ok -- and the connector unreachable from ChatGPT the whole time.

Status semantics: "fail" breaks a tool or the connection and exits 1;
"warn" is degraded but working; "ok" carries the measured value.
"""

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from binnacle import jobs, logstats, uplink
from binnacle.config import CONFIG_FILE_ENV, DEFAULT_CONFIG_FILE, get_settings

Status = Literal["ok", "warn", "fail"]
Systemctl = Callable[..., "subprocess.CompletedProcess[str]"]


@dataclass(slots=True)
class Check:
    group: str
    status: Status
    detail: str
    hint: str = ""


def ok(group: str, detail: str) -> Check:
    return Check(group, "ok", detail)


def warn(group: str, detail: str, hint: str = "") -> Check:
    return Check(group, "warn", detail, hint)


def fail(group: str, detail: str, hint: str = "") -> Check:
    return Check(group, "fail", detail, hint)


# -- systemd helpers ---------------------------------------------------------


def systemctl(*args: str) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(
        ["systemctl", "--user", *args], capture_output=True, text=True, check=False
    )


def unit_state(unit: str, run: Systemctl = systemctl) -> str:
    return run("is-active", unit).stdout.strip() or "unknown"


def unit_property(unit: str, prop: str, run: Systemctl = systemctl) -> str:
    return run("show", unit, "-p", prop, "--value").stdout.strip()


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
    prod_unit: str,
    dev_unit: str,
    run: Systemctl = systemctl,
    linger: Callable[[], bool | None] = linger_enabled,
) -> tuple[list[Check], str | None]:
    """Returns the checks and the name of the active server unit, if any."""
    states = {u: unit_state(u, run) for u in (prod_unit, dev_unit)}
    active = [u for u, s in states.items() if s == "active"]
    summary = ", ".join(f"{u}: {s}" for u, s in states.items())
    out: list[Check] = []
    if not active:
        out.append(
            fail(
                "units",
                f"no server unit active ({summary})",
                "run `binnacle mode prod`",
            )
        )
        return out, None
    if len(active) > 1:
        out.append(
            fail(
                "units",
                f"both server units active ({summary}); they fight for the port",
                "add Conflicts= to both units, then `binnacle mode prod|dev`",
            )
        )
    else:
        out.append(ok("units", f"server active ({summary})"))
    unit = active[0]
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


_INIT = json.dumps(
    {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "binnacle-doctor", "version": "0"},
        },
    }
).encode()


def _post_initialize(url: str, authorization: str | None, timeout: float) -> int | None:
    """HTTP status of an MCP initialize, or None when nothing answers."""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if authorization is not None:
        headers["Authorization"] = authorization
    req = urllib.request.Request(url, data=_INIT, headers=headers, method="POST")
    try:
        # url is built from the fixed http:// literal plus local settings, so
        # no file:/ or custom scheme can reach here.
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
            return int(resp.status)
    except urllib.error.HTTPError as e:
        return e.code
    except OSError:
        return None


def check_endpoint(url: str, token_file: Path, timeout: float = 5.0) -> list[Check]:
    anon = _post_initialize(url, None, timeout)
    if anon is None:
        return [
            fail("endpoint", f"nothing answers at {url}", "is the server unit running?")
        ]
    out: list[Check] = []
    if anon == 401:
        out.append(ok("endpoint", f"{url} refuses an unauthenticated initialize (401)"))
    elif anon == 200:
        out.append(fail("endpoint", f"{url} accepts an initialize WITHOUT a token"))
    else:
        out.append(warn("endpoint", f"unauthenticated initialize returned HTTP {anon}"))
    try:
        header = token_file.read_text(encoding="utf-8").strip()
    except OSError:
        return out  # the token check already reported it
    if not header.startswith("Bearer "):
        header = "Bearer " + header
    auth = _post_initialize(url, header, timeout)
    if auth == 200:
        out.append(ok("endpoint", "initialize with the token file succeeds (200)"))
    elif auth in (401, 403):
        out.append(
            fail(
                "endpoint",
                f"the server rejects the token file (HTTP {auth})",
                "the running server loaded a different token; restart it "
                "(`systemctl --user restart <server unit>`)",
            )
        )
    else:
        out.append(warn("endpoint", f"authenticated initialize returned HTTP {auth}"))
    return out


def check_tunnel(
    unit: str,
    config_file: Path,
    token_file: Path,
    server_url: str,
    run: Systemctl = systemctl,
    timeout: float = 5.0,
    server_unit: str | None = None,
) -> list[Check]:
    out: list[Check] = []
    state = unit_state(unit, run)
    if state == "active":
        out.append(ok("tunnel", f"{unit} active"))
    else:
        out.append(
            fail(
                "tunnel",
                f"{unit} is {state}; ChatGPT cannot reach the server",
                f"systemctl --user start {unit}",
            )
        )
    if server_unit is not None:
        after = unit_property(unit, "After", run).split()
        if server_unit in after:
            out.append(ok("tunnel", f"{unit} starts after {server_unit}"))
        else:
            out.append(
                warn(
                    "tunnel",
                    f"{unit} is not ordered after {server_unit}",
                    f"add After={server_unit} to the tunnel unit",
                )
            )
    if not config_file.exists():
        out.append(
            fail(
                "tunnel",
                f"config missing at {config_file}",
                "write it from the tunnel account",
            )
        )
        return out
    try:
        cfg = json.loads(config_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        out.append(
            warn("tunnel", f"config at {config_file} is not JSON ({e}); not inspected")
        )
        return out
    mcp_cfg = cfg.get("mcp", {}) if isinstance(cfg, dict) else {}
    urls = [u.get("url") for u in mcp_cfg.get("server_urls", []) if isinstance(u, dict)]
    if server_url in urls:
        out.append(ok("tunnel", f"config forwards to {server_url}"))
    else:
        out.append(
            fail(
                "tunnel",
                f"config forwards to {urls or 'nothing'}, server listens at {server_url}",
                f"set mcp.server_urls[].url to {server_url} in {config_file}",
            )
        )
    expected = f"file:{token_file}"
    for key in ("extra_headers", "discovery_extra_headers"):
        value = (mcp_cfg.get(key) or {}).get("Authorization")
        if value == expected:
            out.append(ok("tunnel", f"mcp.{key} reads the token file"))
        else:
            out.append(
                fail(
                    "tunnel",
                    f"mcp.{key}.Authorization is {value!r}, expected {expected!r}",
                    f"fix {config_file} and restart {unit}",
                )
            )
    url_file = (
        ((cfg.get("health") or {}).get("url_file")) if isinstance(cfg, dict) else None
    )
    if url_file:
        out.append(_check_tunnel_health(Path(url_file), timeout))
    return out


def _check_tunnel_health(url_file: Path, timeout: float) -> Check:
    try:
        url = url_file.read_text(encoding="utf-8").strip()
    except OSError:
        return warn(
            "tunnel", f"health URL file {url_file} unreadable (tunnel not started?)"
        )
    if not url.startswith("http://127.0.0.1") and not url.startswith(
        "http://localhost"
    ):
        return warn("tunnel", f"health URL {url!r} is not local; not probed")
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # nosec B310
            return ok("tunnel", f"health endpoint {url} answers HTTP {resp.status}")
    except urllib.error.HTTPError as e:
        return ok("tunnel", f"health endpoint {url} answers HTTP {e.code}")
    except OSError:
        return warn(
            "tunnel", f"health endpoint {url} does not answer (stale url file?)"
        )


def _tail_lines(path: Path, max_bytes: int = 512 * 1024) -> list[str]:
    """Last lines of a file, without reading all of it.

    The tunnel log runs to megabytes within a day; only the tail says
    anything about the poller's current state.
    """
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - max_bytes))
            raw = fh.read()
    except OSError:
        return []
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    # A partial first line is likely when we seek into the middle.
    return lines[1:] if size > max_bytes and lines else lines


#: Tunnel log messages that decide whether the poller is reaching OpenAI.
#: Both a failed poll and a timed-out poll are the poller backing off: in
#: the log, 132 of 186 timeout runs (2026-09-13/14) end with "poller
#: recovered", and during a wedge of the active route the poller logged
#: only timeouts for five minutes -- ChatGPT saw the connector offline
#: while an earlier version of this check counted nothing.
_POLL_DOWN = ("poll failed; backing off", "poll timed out; backing off")
_POLL_UP = ("poller recovered; polling operational", "🟢 tunnel-client started")
_POLL_WORK = "dispatcher forwarded command to MCP server"


@dataclass(frozen=True)
class TunnelLogStatus:
    """What the tail of the tunnel's log says right now."""

    #: Trailing failed/timed-out polls, and when the run began.
    trailing: int
    first_failure: str
    #: Time of the last line at all, and of the last command forwarded to
    #: the MCP server.
    last_time: str
    last_forwarded: str


def scan_tunnel_log(log_file: Path) -> TunnelLogStatus:
    """Read the tail of the tunnel's own log. A failed poll and a timed-out
    poll both count (the poller backs off after either); forwarded work or
    a recovery line ends a run. A single timeout is a blip; the callers'
    threshold of three is what makes it an outage."""
    trailing = 0
    first_failure = ""
    last_time = ""
    last_forwarded = ""
    for line in _tail_lines(log_file):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = rec.get("msg", "")
        stamp = rec.get("time", "")
        if stamp:
            last_time = stamp
        if msg in _POLL_DOWN:
            if not trailing:
                first_failure = stamp
            trailing += 1
        elif msg in _POLL_UP or msg == _POLL_WORK:
            trailing = 0
            first_failure = ""
            if msg == _POLL_WORK and stamp:
                last_forwarded = stamp
    return TunnelLogStatus(trailing, first_failure, last_time, last_forwarded)


def poller_status(log_file: Path) -> tuple[int, str, str]:
    """(trailing poll failures, time of the first one, last log time)."""
    status = scan_tunnel_log(log_file)
    return status.trailing, status.first_failure, status.last_time


def check_tunnel_poller(log_file: Path, min_failures: int = 3) -> list[Check]:
    """Is the tunnel actually reaching OpenAI right now?

    This is the one check that sees what ChatGPT sees. Every other tunnel
    check is local: the unit can be active, the config correct and the
    local health port answering while the poller has been failing for an
    hour because the uplink is wedged. That is exactly the 2026-09-12
    outage, during which `doctor` reported all-ok.

    `poll timed out; backing off` counts like `poll failed`: measured on
    2026-09-14, a run of timeouts is what the tunnel logs while the
    uplink is wedged, and it ends with `poller recovered`.
    """
    if not log_file.exists():
        return [warn("poller", f"tunnel log {log_file} not found; poller not checked")]
    trailing, first_failure, last_time = poller_status(log_file)
    if trailing >= min_failures:
        return [
            fail(
                "poller",
                f"tunnel poll to OpenAI failing: {trailing} consecutive failures "
                f"since {first_failure or 'unknown'}; ChatGPT sees the connector offline",
                "check the uplink (binnacle doctor reports it above); "
                "check the uplink and tunnel path; move traffic to a working route "
                "before restarting the tunnel",
            )
        ]
    if trailing:
        return [
            warn(
                "poller",
                f"tunnel poll to OpenAI failing ({trailing} consecutive, "
                f"below the {min_failures} threshold)",
            )
        ]
    return [ok("poller", f"tunnel poll to OpenAI healthy (last log entry {last_time})")]


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


def check_uplink(
    host: str = uplink.UPSTREAM_HOST,
    timeout: float = 3.0,
    run: uplink.Run = uplink._run,
    fallback_nameserver: str | None = None,
) -> list[Check]:
    """Does the route traffic takes actually carry traffic?

    Probes every default route end to end. A wedged active route is a
    FAIL: the host is up, the server is up, and nothing can reach it.
    """
    routes = uplink.default_routes(run)
    if not routes:
        return [warn("uplink", "no default route with a gateway and source address")]
    probes = uplink.probe_all(
        routes,
        host=host,
        timeout=timeout,
        run=run,
        fallback_nameserver=fallback_nameserver,
    )
    active = uplink.active_route(routes)
    out: list[Check] = []
    for route in routes:
        probe = probes.get(route.dev)
        if probe is None:
            continue
        is_active = active is not None and route.dev == active.dev
        role = "active" if is_active else "standby"
        if probe.healthy:
            out.append(ok("uplink", f"{role} {route.label}: {probe.summary()}"))
        elif probe.wedged and is_active:
            out.append(
                fail(
                    "uplink",
                    f"active {route.label} carries nothing: {probe.summary()}",
                    "another route must take over; inspect the route and uplink state",
                )
            )
        elif probe.wedged:
            out.append(
                warn(
                    "uplink",
                    f"standby {route.label} carries nothing: {probe.summary()}",
                    f"no impact while {active.dev if active else '?'} is healthy",
                )
            )
        else:
            deepest = probe.deepest_ok or "nothing"
            out.append(
                warn(
                    "uplink",
                    f"{role} {route.label} degraded: {probe.summary()} "
                    f"(deepest layer reached: {deepest})",
                    probe.errors.get(probe.first_failure or "", ""),
                )
            )
    return out


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


def _job_state_safe(job_id: str) -> dict | None:
    try:
        return jobs.job_state(job_id)
    except (KeyError, OSError):
        return None


def check_journal(
    unit: str,
    since: str,
    fetch: Callable[[str, str], str] = lambda u, s: logstats.fetch_journal(u, s),
) -> list[Check]:
    try:
        text = fetch(unit, since)
    except SystemExit as e:
        return [warn("journal", f"journal unavailable: {e}")]
    errors = sum(1 for line in text.splitlines() if "ERROR" in line)
    tracebacks = sum(1 for line in text.splitlines() if line.startswith("Traceback"))
    if not errors and not tracebacks:
        return [ok("journal", f"no errors in the {unit} journal since {since}")]
    return [
        warn(
            "journal",
            f"{errors} error line(s) and {tracebacks} traceback(s) since {since}",
            f"journalctl --user -u {unit} --since='{since}' -p err",
        )
    ]


# -- aggregate ---------------------------------------------------------------


@dataclass(slots=True)
class Deployment:
    """Names the doctor needs; the CLI fills these from its constants."""

    prod_unit: str
    dev_unit: str
    tunnel_unit: str
    tunnel_config: Path
    token_file: Path
    server_url: str
    user_bin: Path


def _tunnel_log_file(config_file: Path) -> Path | None:
    """The tunnel's own log path, as its config declares it."""
    try:
        cfg = json.loads(config_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    path = ((cfg.get("log") or {}).get("file")) if isinstance(cfg, dict) else None
    return Path(path) if path else None


def run_all(dep: Deployment, since: str = "-1 hour", probe: bool = True) -> list[Check]:
    """Every check, in the order a request travels.

    `probe=False` skips the checks that touch the network, for tests and
    for a quick local-only look.
    """
    s = get_settings()
    checks: list[Check] = []
    checks += check_config()
    checks += check_token(dep.token_file)
    unit_checks, active = check_units(dep.prod_unit, dep.dev_unit)
    checks += unit_checks
    if active:
        checks += check_service_env(active, s.rg_bin, dep.user_bin)
    checks += check_endpoint(dep.server_url, dep.token_file)
    checks += check_tunnel(
        dep.tunnel_unit,
        dep.tunnel_config,
        dep.token_file,
        dep.server_url,
        server_unit=active,
    )
    # The uplink and the poller are the two checks that see past localhost.
    if probe:
        checks += check_uplink()
    log_file = _tunnel_log_file(dep.tunnel_config)
    if log_file is not None:
        checks += check_tunnel_poller(log_file)
    checks += check_boot()
    checks += check_jobs(s.jobs.dir)
    if active:
        checks += check_journal(active, since)
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
