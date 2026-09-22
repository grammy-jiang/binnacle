"""Managed systemd user unit for the stable command owner."""

from collections.abc import Mapping
from pathlib import Path

from binnacle import units

JOBS_UNIT = "binnacle-jobs.service"
OWNER = "binnacle"

JOBS_UNIT_TEMPLATE = """\
[Unit]
Description=Binnacle command job manager

[Service]
Type=notify
NotifyAccess=main
ExecStart={exec_start}
TimeoutStartSec=30
Restart=always
RestartSec=1
KillMode=control-group
RuntimeDirectory=binnacle
RuntimeDirectoryMode=0700
UMask=0077

[Install]
WantedBy=default.target
"""


def job_manager_unit_spec(params: Mapping[str, str]) -> units.UnitSpec:
    mode = params.get("mode", "")
    if mode not in {"dev", "prod"}:
        raise units.UnitError(f"unknown jobs mode {mode!r}; expected dev or prod")
    binary = params.get("jobs")
    if not binary:
        raise units.UnitError("job manager unit needs the `jobs` executable parameter")
    return units.UnitSpec(
        JOBS_UNIT,
        OWNER,
        JOBS_UNIT_TEMPLATE.format(exec_start=binary),
        dict(params),
    )


def render_job_manager_unit(params: Mapping[str, str]) -> str:
    return units.render(job_manager_unit_spec(params))


def job_manager_params(mode: str, repo: Path | None) -> dict[str, str]:
    if mode == "dev":
        if repo is None:
            raise units.UnitError("development mode needs the checkout: --dev <repo>")
        binary = repo.expanduser().resolve() / ".venv" / "bin" / "binnacle-jobs"
    elif mode == "prod":
        binary = units.resolve_executable("binnacle-jobs")
    else:
        raise units.UnitError(f"unknown jobs mode {mode!r}; expected dev or prod")
    return {"mode": mode, "jobs": str(binary)}
