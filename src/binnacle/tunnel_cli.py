"""Host-specific tunnel command line: the ChatGPT side of the deployment.

`binnacle-tunnel.service` runs the OpenAI tunnel client through which
ChatGPT reaches the MCP server. Every other agent connects to the server
directly, so the unit is not the server's business: `binnacle setup`
never writes it; this companion does. `setup` writes the unit (adopting a
hand-written one on request), `restart` bounces it at a quiet moment,
`doctor` verifies the unit, the profile and the poller. May depend on
Binnacle core; core must not import it. The tunnel-client binary, the
profile config and the ChatGPT connector stay manual by design.
"""

import json
import time
from pathlib import Path
from typing import Annotated

import cyclopts

from binnacle import units
from binnacle.cli import BACKUP_DIR, _systemctl, _unit_state
from binnacle.server_unit import SERVER_UNIT
from binnacle.tunnel_unit import (
    PROFILE,
    TUNNEL_UNIT,
    profile_config,
    profile_env_file,
    tunnel_unit_spec,
)

app = cyclopts.App(
    name="binnacle-tunnel",
    help="ChatGPT tunnel companion for Binnacle: the unit that runs the OpenAI tunnel client.",
)


def _params(profile: str) -> dict[str, str]:
    """The unit's parameters for `profile`; UnitError says what is missing."""
    tunnel_bin = units.resolve_executable("tunnel-client")
    cfg_path = profile_config(profile)
    if not cfg_path.exists():
        raise units.UnitError(
            f"tunnel profile config {cfg_path} does not exist; write it from your "
            "tunnel account settings first (it is never generated here)"
        )
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise units.UnitError(
            f"tunnel profile config {cfg_path} is not readable JSON ({e})"
        ) from e
    health = cfg.get("health") if isinstance(cfg, dict) else None
    url_file = health.get("url_file") if isinstance(health, dict) else None
    if not url_file:
        raise units.UnitError(
            f"{cfg_path} has no health.url_file; the unit's readiness wait needs it"
        )
    env_file = profile_env_file(profile)
    if not env_file.exists():
        raise units.UnitError(
            f"environment file {env_file} does not exist (it holds the control-plane "
            "API key reference)"
        )
    return {
        "tunnel": str(tunnel_bin),
        "profile_dir": str(cfg_path.parent),
        "profile": profile,
        "env_file": str(env_file),
        "url_file": str(url_file),
        "server_unit": SERVER_UNIT,
        "home": str(Path.home()),
    }


@app.command
def setup(dry_run: bool = False, adopt: bool = False, profile: str = PROFILE) -> None:
    """Provision the tunnel's systemd user unit.

    Needs the tunnel-client binary on PATH, the profile's config (written
    from the tunnel account) and its environment file.

    Parameters
    ----------
    dry_run
        Print every action, and the unit diff, instead of performing them.
    adopt
        Take over a unit file no binnacle setup command wrote (a hand-written
        one), after reviewing the diff `--dry-run` shows. It is backed up
        first.
    profile
        The tunnel-client profile the unit runs.
    """
    try:
        spec = tunnel_unit_spec(_params(profile))
    except units.UnitError as e:
        print(e)
        raise SystemExit(1) from None
    unit_path = units.UNIT_DIR / TUNNEL_UNIT
    plan = units.plan_write(unit_path, spec, adopt=adopt)
    if plan.diff:
        print(plan.diff + "\n")
    if plan.action == "refuse":
        print(plan.reason)
        raise SystemExit(1)

    actions: list[str] = []

    def act(description: str, fn: object) -> None:
        actions.append(description)
        if not dry_run and callable(fn):
            fn()

    if plan.action == "unchanged":
        actions.append(f"keep {unit_path} (already what setup writes)")
    else:
        act(
            f"{'write' if plan.action == 'create' else 'rewrite'} {unit_path}",
            lambda: units.write_unit(unit_path, plan, BACKUP_DIR),
        )
    act("systemctl --user daemon-reload", lambda: _systemctl("daemon-reload"))
    act(
        f"systemctl --user enable --now {TUNNEL_UNIT}",
        lambda: _systemctl("enable", "--now", TUNNEL_UNIT),
    )
    prefix = "would " if dry_run else ""
    for description in actions:
        print(f"{prefix}{description}")
    if dry_run:
        print("\ndry run: nothing was changed.")
        return
    print("\ntunnel unit is configured.")
    if plan.action == "rewrite" and _unit_state(TUNNEL_UNIT) == "active":
        print(
            f"{TUNNEL_UNIT} is running on the previous unit file; restart it at a "
            "quiet moment: `binnacle-tunnel restart`"
        )


@app.command
def restart(force: bool = False, window_s: float = 30.0) -> None:
    """Restart the tunnel unit at a quiet moment.

    Quiet means no command forwarded by the tunnel and no tool call seen by
    the server in the last WINDOW-S seconds: a restart drops the reply of a
    call in flight. `--force` overrides. The unit's readiness wait makes the
    restart return once the new instance answers /readyz (10 s at most).
    """
    from binnacle import tunnel_doctor as checks

    if not force:
        cfg = checks.read_profile(profile_config(PROFILE))
        busy = checks.tunnel_busy_reasons(window_s, checks.log_file_of(cfg))
        if busy:
            print("not a quiet moment for a restart:")
            for reason in busy:
                print(f"  {reason}")
            print("retry later, or pass --force")
            raise SystemExit(1)
    started = time.monotonic()
    proc = _systemctl("restart", TUNNEL_UNIT, check=False)
    if proc.returncode != 0:
        print(f"failed to restart {TUNNEL_UNIT}: {proc.stderr.strip()}")
        raise SystemExit(1)
    elapsed = time.monotonic() - started
    print(f"{TUNNEL_UNIT} restarted in {elapsed:.1f} s and {_unit_state(TUNNEL_UNIT)}")


@app.command
def doctor(as_json: Annotated[bool, cyclopts.Parameter(name="--json")] = False) -> None:
    """Check the tunnel side: the unit file against what setup writes, the
    process it started, the profile config, the health port and the poller."""
    from binnacle import doctor as core_doctor
    from binnacle import tunnel_doctor as checks

    results = checks.run_all()
    text, code = (core_doctor.render_json if as_json else core_doctor.render)(results)
    print(text)
    raise SystemExit(code)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
