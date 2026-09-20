"""The server's systemd unit: one name, content rendered for the mode.

`binnacle-mcp.service` runs either the checkout with auto-reload
(development) or the installed `binnacle serve` (production). Keeping one
unit name means the tunnel, the journal readers and the watchdog need no
change when the mode changes, and the mode survives a reboot. Shared by
`binnacle setup` and `binnacle mode` (write it) and `binnacle doctor`
(re-renders it from the marker line and reports drift).
"""

from collections.abc import Mapping
from pathlib import Path

from binnacle import units

SERVER_UNIT = "binnacle-mcp.service"
OWNER = "binnacle"

SERVER_UNIT_TEMPLATE = """\
[Unit]
Description=Binnacle FastMCP server ({description})
After=network.target

[Service]
Type=simple
{working_directory}ExecStart={exec_start}
# Hold the unit in "activating" until the port answers, so After= dependents
# (the tunnel) and `systemctl restart` callers see a server that is listening.
ExecStartPost=/bin/bash -c 'for i in $(seq 1 300); do (exec 3<>/dev/tcp/127.0.0.1/{port}) 2>/dev/null && exit 0; sleep 0.1; done; echo "binnacle: port {port} not listening after 30 s" >&2; exit 1'
Restart={restart}
RestartSec=2
UMask=0077

[Install]
WantedBy=default.target
"""


def server_unit_spec(params: Mapping[str, str]) -> units.UnitSpec:
    """The server unit for `params`: `mode` (dev or prod), `host`, `port`,
    and `repo` (dev: the checkout, run through its venv with auto-reload)
    or `binnacle` (prod: the installed executable, `serve`, no reload).
    The development command line is the one the host ran hand-written from
    2026-09-03 to 2026-09-20; the two uvicorn flags select the uvloop and
    httptools stack that `serve` also insists on."""
    mode = params.get("mode", "")
    host = params.get("host", "127.0.0.1")
    port = params.get("port", "")
    if mode == "dev":
        repo = params["repo"]
        exec_start = (
            f"{repo}/.venv/bin/uvicorn binnacle.server:app --host {host} "
            f"--port {port} --reload --loop uvloop --http httptools"
        )
        body = SERVER_UNIT_TEMPLATE.format(
            description="development: checkout with auto-reload",
            working_directory=f"WorkingDirectory={repo}\n",
            exec_start=exec_start,
            port=port,
            restart="on-failure",
        )
    elif mode == "prod":
        binary = params["binnacle"]
        body = SERVER_UNIT_TEMPLATE.format(
            description="production: installed package, no reload",
            working_directory="",
            exec_start=f"{binary} serve --host {host} --port {port}",
            port=port,
            restart="always",
        )
    else:
        raise units.UnitError(f"unknown server mode {mode!r}; expected dev or prod")
    return units.UnitSpec(SERVER_UNIT, OWNER, body, dict(params))


def render_server_unit(params: Mapping[str, str]) -> str:
    """What `setup` writes for the parameters a unit's marker records."""
    return units.render(server_unit_spec(params))


def server_params(mode: str, repo: Path | None, host: str, port: int) -> dict[str, str]:
    params = {"mode": mode, "host": host, "port": str(port)}
    if repo is not None:
        # Recorded in every mode, so `mode dev` after `mode prod` needs no
        # --repo: the marker remembers the checkout.
        params["repo"] = str(repo.expanduser().resolve())
    if mode == "dev":
        if repo is None:
            raise units.UnitError("development mode needs the checkout: --dev <repo>")
    else:
        params["binnacle"] = str(units.resolve_executable("binnacle"))
    return params
