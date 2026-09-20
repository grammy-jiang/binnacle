"""The tunnel companion's systemd unit: name, template, rendering.

`binnacle-tunnel.service` runs the OpenAI tunnel client that gives ChatGPT
its way in. That is ChatGPT's side of the deployment, not the server's:
every other agent reaches the server directly, so the unit belongs to the
`binnacle-tunnel` companion and `binnacle setup` never touches it. May
depend on Binnacle core; core must not import it.
"""

from collections.abc import Mapping
from pathlib import Path

from binnacle import units

TUNNEL_UNIT = "binnacle-tunnel.service"
OWNER = "binnacle-tunnel"
PROFILE = "binnacle"
PARAMS = (
    "tunnel",
    "profile_dir",
    "profile",
    "env_file",
    "url_file",
    "server_unit",
    "home",
)

# `$$` is systemd's escape for a literal `$`: it substitutes `$NAME` from the
# unit's environment even inside quotes, so the readiness script's own
# variables must not look like environment references.
TUNNEL_UNIT_TEMPLATE = """\
[Unit]
Description=Binnacle OpenAI MCP tunnel client
Wants={server_unit}
After={server_unit}

[Service]
Type=simple
WorkingDirectory={home}
EnvironmentFile={env_file}
ExecStart={tunnel} run --profile-dir {profile_dir} --profile {profile}
# Hold the unit in "activating" until the new instance's health server
# answers /readyz (it rewrites its URL file on every start), so a
# `systemctl restart` -- token rotate, the watchdog's failover -- returns to
# a tunnel that polls. Bounded at 10 s and never failing the unit: a WAN
# outage must not become a restart loop.
ExecStartPost=/bin/bash -c 'm=$$(mktemp); end=$$((SECONDS+10)); while [ $$SECONDS -lt $$end ]; do if [ "{url_file}" -nt "$$m" ] && curl -fsS -m 1 "$$(cat "{url_file}")/readyz" >/dev/null 2>&1; then rm -f "$$m"; exit 0; fi; sleep 0.2; done; rm -f "$$m"; exit 0'
Restart=always
RestartSec=5
UMask=0077

[Install]
WantedBy=default.target
"""


def profile_dir() -> Path:
    return Path.home() / ".config" / "tunnel-client"


def profile_config(profile: str = PROFILE) -> Path:
    """The profile's config, written from the tunnel account, never generated."""
    return profile_dir() / f"{profile}.yaml"


def profile_env_file(profile: str = PROFILE) -> Path:
    """The profile's environment file: the control-plane API key reference."""
    return profile_dir() / f"{profile}-tunnel.env"


def tunnel_unit_spec(params: Mapping[str, str]) -> units.UnitSpec:
    """The unit for `params` (every name in PARAMS)."""
    missing = [k for k in PARAMS if not params.get(k)]
    if missing:
        raise units.UnitError(
            f"the tunnel unit needs {', '.join(missing)}; run `binnacle-tunnel setup`"
        )
    chosen = {k: params[k] for k in PARAMS}
    return units.UnitSpec(
        TUNNEL_UNIT, OWNER, TUNNEL_UNIT_TEMPLATE.format(**chosen), chosen
    )


def render_tunnel_unit(params: Mapping[str, str]) -> str:
    return units.render(tunnel_unit_spec(params))
