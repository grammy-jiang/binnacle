"""binnacle command line -- serve, setup, mode, doctor, stats, token.

The server itself lives in binnacle.server; this module only wires it to
subcommands and provisions the deployment pieces that are ours to manage:
the token and the server's systemd user unit. The unit is one file,
`binnacle-mcp.service`, whose content `setup` and `mode` render for the
mode in use (development: the checkout with auto-reload; production: the
installed `binnacle serve`), so the tunnel, the journal readers and the
watchdog key on one name and the mode survives a reboot. The tunnel-client
binary and every ChatGPT UI step stay manual by design.
"""

import json
import re
import secrets
import shutil
import subprocess
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

import cyclopts

from binnacle import units
from binnacle.config import get_settings
from binnacle.server_unit import (
    SERVER_UNIT,
    render_server_unit,
    server_params,
    server_unit_spec,
)

app = cyclopts.App(
    name="binnacle",
    help="MCP server that lets AI agents work on a Raspberry Pi.",
)

TOKEN_FILE = get_settings().auth.token_file
UNIT_DIR = units.UNIT_DIR
TUNNEL_UNIT = "binnacle-tunnel.service"
TUNNEL_CONFIG = Path.home() / ".config" / "tunnel-client" / "binnacle.yaml"
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


def _tunnel_health_url() -> str | None:
    """The tunnel's local health base URL, from its config's health.url_file."""
    try:
        cfg = json.loads(TUNNEL_CONFIG.read_text(encoding="utf-8"))
        url_file = Path(cfg["health"]["url_file"])
        return url_file.read_text(encoding="utf-8").strip() or None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _parse_rfc3339(text: str) -> datetime:
    """fromisoformat that tolerates Go's nanosecond fractions and 'Z'."""
    text = text.replace("Z", "+00:00")
    m = re.match(r"^(.*T\d\d:\d\d:\d\d)(\.\d+)?(.*)$", text)
    if m:
        frac = (m.group(2) or ".0")[:7].ljust(7, "0")  # exactly 6 digits
        text = f"{m.group(1)}{frac}{m.group(3)}"
    return datetime.fromisoformat(text)


def _wait_tunnel_ready(
    since: float,
    timeout_s: float = 30.0,
    health_url: Callable[[], str | None] = _tunnel_health_url,
) -> str:
    """Block until the restarted tunnel reports ready and its MCP probe is ok.

    Readiness is read from the tunnel's health server: /api/status must
    come from an instance started after `since` (a stale url file still
    points at the old instance) with channel "main" probe_status ok, and
    /readyz must answer 200. Returns a one-line description of the outcome;
    a timeout is reported, not raised, because the restart itself succeeded.
    """
    import urllib.error
    import urllib.request

    deadline = time.monotonic() + timeout_s
    last = "health URL file not written yet"
    while time.monotonic() < deadline:
        base = health_url()
        if base:
            try:
                with urllib.request.urlopen(base + "/api/status", timeout=2) as r:  # nosec B310
                    status = json.loads(r.read())
                started = _parse_rfc3339(status["started_at"]).timestamp()
                probe = next(
                    (
                        c.get("probe_status")
                        for c in status.get("channels", [])
                        if c.get("name") == "main"
                    ),
                    None,
                )
                if started < since:
                    last = "health URL still points at the previous tunnel instance"
                elif probe != "ok":
                    last = f"tunnel up, MCP probe status {probe!r}"
                else:
                    with urllib.request.urlopen(base + "/readyz", timeout=2) as r:  # nosec B310
                        if r.status == 200:
                            return f"tunnel ready ({base}, MCP probe ok)"
                    last = "tunnel /readyz not 200"
            except (OSError, ValueError, KeyError, TypeError) as e:
                last = f"tunnel health not answering yet ({e.__class__.__name__})"
        time.sleep(0.25)
    return f"tunnel not ready after {timeout_s:g} s: {last}"


def _systemctl(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["systemctl", "--user", *args],
        capture_output=True,
        text=True,
        check=check,
    )


def _unit_state(unit: str) -> str:
    proc = _systemctl("is-active", unit, check=False)
    return proc.stdout.strip() or "unknown"


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


@app.command
def setup(
    dev: Path | None = None,
    port: int = get_settings().serve.port,
    dry_run: bool = False,
    adopt: bool = False,
) -> None:
    """Provision the server side: the token and the systemd user unit.

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

    # 1. Token (0600, referenced by the server and by the tunnel config).
    if not TOKEN_FILE.exists():
        act(f"generate bearer token at {TOKEN_FILE} (mode 0600)", _write_token)
    else:
        actions.append(f"keep existing token at {TOKEN_FILE}")

    # 2. The unit, rendered for the mode; never over a stranger's file.
    mode = "dev" if dev is not None else "prod"
    try:
        spec = server_unit_spec(
            server_params(mode, dev, get_settings().serve.host, port)
        )
    except units.UnitError as e:
        print(e)
        raise SystemExit(1) from None
    unit_path = UNIT_DIR / SERVER_UNIT
    plan = units.plan_write(unit_path, spec, adopt=adopt)
    if plan.diff:
        print(plan.diff + "\n")
    if plan.action == "refuse":
        print(plan.reason)
        raise SystemExit(1)
    if plan.action == "unchanged":
        actions.append(f"keep {unit_path} (already what setup writes, {mode} mode)")
    else:
        verb = "write" if plan.action == "create" else "rewrite"
        act(
            f"{verb} {unit_path} ({mode} mode; a copy of the old file goes to "
            f"{BACKUP_DIR})"
            if plan.action == "rewrite"
            else f"{verb} {unit_path} ({mode} mode)",
            lambda: units.write_unit(unit_path, plan, BACKUP_DIR),
        )

    # 3. Tunnel config, only when the tunnel-client binary is present.
    tunnel_bin = shutil.which("tunnel-client")
    if tunnel_bin is None:
        actions.append(
            "tunnel-client not found on PATH: skipping tunnel config; install "
            "it and re-run `binnacle setup` to enable the tunnel"
        )
    elif TUNNEL_CONFIG.exists():
        actions.append(f"keep existing tunnel config at {TUNNEL_CONFIG}")
    else:
        actions.append(
            f"tunnel-client found at {tunnel_bin} but {TUNNEL_CONFIG} does not "
            f"exist; write it from your tunnel account settings, then enable "
            f"{TUNNEL_UNIT}"
        )

    # 4. Enable and start.
    act("systemctl --user daemon-reload", lambda: _systemctl("daemon-reload"))
    act(
        f"systemctl --user enable --now {SERVER_UNIT}",
        lambda: _systemctl("enable", "--now", SERVER_UNIT),
    )
    act(
        "loginctl enable-linger (service survives logout and reboot)",
        lambda: subprocess.run(["loginctl", "enable-linger"], check=True),
    )

    prefix = "would " if dry_run else ""
    for a in actions:
        print(f"{prefix}{a}")
    if dry_run:
        print("\ndry run: nothing was changed.")
        return
    print("\nserver side is configured. Remaining manual steps: install")
    print("tunnel-client (if missing) and add the connector in ChatGPT.")
    if plan.action == "rewrite" and _unit_state(SERVER_UNIT) == "active":
        print(
            f"{SERVER_UNIT} is running on the previous unit file; restart it at "
            f"a quiet moment: `binnacle mode {mode}`"
        )


def _current_marker() -> units.Marker | None:
    unit_path = UNIT_DIR / SERVER_UNIT
    if not unit_path.exists():
        return None
    return units.read_marker(unit_path.read_text(encoding="utf-8"))


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
    development mode. The restart is refused while a background job is
    running or a tool call arrived in the last 30 s, because a unit
    restart kills the jobs in its cgroup and fails the calls in flight;
    `--force` overrides. Run `chatgpt-refresh` afterwards when the two
    instances differ in tool surface.
    """
    marker = _current_marker()
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
    checkout = repo or (Path(known["repo"]) if "repo" in known else None)
    if target == "dev" and checkout is None:
        print("development mode needs the checkout: `binnacle mode dev --repo <path>`")
        raise SystemExit(1)
    try:
        port = int(known.get("port") or get_settings().serve.port)
        spec = server_unit_spec(
            server_params(
                target, checkout, known.get("host") or get_settings().serve.host, port
            )
        )
    except units.UnitError as e:
        print(e)
        raise SystemExit(1) from None
    unit_path = UNIT_DIR / SERVER_UNIT
    plan = units.plan_write(unit_path, spec)
    if plan.action == "refuse":
        print(plan.reason)
        raise SystemExit(1)
    if not force:
        from binnacle import doctor as checks

        busy = checks.server_busy_reasons(SERVER_UNIT, get_settings().jobs.dir)
        if busy:
            print("not a quiet moment for a restart:")
            for reason in busy:
                print(f"  {reason}")
            print("retry later, or pass --force")
            raise SystemExit(1)
    if plan.action == "rewrite":
        if plan.diff:
            print(plan.diff + "\n")
        units.write_unit(unit_path, plan, BACKUP_DIR)
        _systemctl("daemon-reload")
    proc = _systemctl("restart", SERVER_UNIT, check=False)
    if proc.returncode != 0:
        print(f"failed to restart {SERVER_UNIT}: {proc.stderr.strip()}")
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
    linger), the running server's PATH (~/.local/bin,
    ripgrep, bash), /mcp auth with and without the token, tunnel unit and
    config, the uplink each default route provides, whether the tunnel's
    poller is reaching OpenAI, the job spool, and recent journal errors.
    Host-specific watchdog diagnostics live in the companion CLI. WARN lines
    are degraded but working and do not change the exit code.

    Parameters
    ----------
    since
        journalctl window for the error scan (--since="-2 hours").
    as_json
        Emit the checks as JSON instead of the text report.
    probe
        Run the network probes (--no-probe for a local-only report).
    """
    from binnacle import doctor as checks

    serve_cfg = get_settings().serve
    dep = checks.Deployment(
        server_unit=SERVER_UNIT,
        unit_path=UNIT_DIR / SERVER_UNIT,
        render_unit=render_server_unit,
        tunnel_unit=TUNNEL_UNIT,
        tunnel_config=TUNNEL_CONFIG,
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

    records, startups = logstats.parse(logstats.fetch_journal(unit, since, until))
    print(
        f"binnacle stats -- unit {unit}, since {since}"
        + (f", until {until}" if until else "")
    )
    print(logstats.render(logstats.analyze(records, startups)))
    if system_resources:
        from binnacle import webminstats

        print("\n" + webminstats.render(webminstats.load(since, until)))


token_app = cyclopts.App(name="token", help="Bearer token operations.")
app.command(token_app)


@token_app.command
def rotate() -> None:
    """Write a new token and restart the server and tunnel services."""
    _write_token()
    print(f"wrote new token to {TOKEN_FILE}")
    for unit in (SERVER_UNIT, TUNNEL_UNIT):
        if _unit_state(unit) == "active":
            started = time.time()
            _systemctl("restart", unit, check=False)
            print(f"restarted {unit}")
            if unit == TUNNEL_UNIT:
                # The tunnel caches the token at startup and re-registers its
                # poller with OpenAI; return only once it can reach the server
                # again, so a chatgpt-refresh right after this call has a chance.
                print(_wait_tunnel_ready(started))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
