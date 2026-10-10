"""Synthetic Linux OS0 parity snapshots; never mutate real managed services."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def blocked(target):
    with tempfile.TemporaryDirectory(prefix="binnacle-os0-import-") as d:
        cfg = Path(d) / "config.toml"
        token = Path(d) / "token"
        token.write_text("os0-capture-token")
        cfg.write_text(
            f'[auth]\ntoken_file = "{token}"\n[jobs]\nowner = "embedded"\ndir = "{d}/jobs"\nsocket_path = "{d}/jobs.sock"\n'
        )
        body = """
import importlib, importlib.abc, sys
class NoLinux(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('binnacle.platform.linux','binnacle.observability.linux')):
            raise ImportError('blocked Linux adapter: '+fullname)
sys.meta_path.insert(0,NoLinux())
importlib.import_module(sys.argv[1])
print('IMPORT_OK')
"""
        env = {k: v for k, v in os.environ.items() if not k.startswith("BINNACLE_")}
        env["BINNACLE_CONFIG_FILE"] = str(cfg)
        run = subprocess.run(
            [sys.executable, "-c", body, target],
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
            cwd=ROOT,
        )
        return {
            "module": target,
            "exit": run.returncode,
            "stdout": run.stdout.strip(),
            "stderr_last_12_lines": "\n".join(run.stderr.splitlines()[-12:]),
        }


def main():
    from binnacle.deployment import job_manager_unit, server_unit, units
    from binnacle.features.commands.job_client import PROTOCOL_VERSION
    from binnacle.features.commands.job_store import META_REQUIRED

    params_dev = {
        "mode": "dev",
        "host": "127.0.0.1",
        "port": "8000",
        "jobs_owner": "manager",
        "repo": "/tmp/binnacle-os0-reference",
    }
    params_prod = {
        "mode": "prod",
        "host": "127.0.0.1",
        "port": "8000",
        "jobs_owner": "manager",
        "binnacle": "/usr/local/bin/binnacle",
    }
    rendered = {
        "mcp_dev": server_unit.render_server_unit(params_dev),
        "mcp_prod": server_unit.render_server_unit(params_prod),
        "jobs_dev": job_manager_unit.render_job_manager_unit(
            {
                "mode": "dev",
                "jobs": "/tmp/binnacle-os0-reference/.venv/bin/binnacle-jobs",
            }
        ),
        "jobs_prod": job_manager_unit.render_job_manager_unit(
            {"mode": "prod", "jobs": "/usr/local/bin/binnacle-jobs"}
        ),
    }
    previews = {}
    with tempfile.TemporaryDirectory(prefix="binnacle-os0-units-") as d:
        target = Path(d) / "binnacle-mcp.service"
        spec = server_unit.server_unit_spec(params_dev)
        for state in ("absent", "foreign", "own"):
            if state == "foreign":
                target.write_text("[Unit]\nDescription=foreign\n")
            elif state == "own":
                target.write_text(rendered["mcp_dev"])
            planned = units.plan_write(target, spec)
            previews[state] = {
                "action": planned.action,
                "reason": planned.reason,
                "diff": planned.diff.replace(d, "<unit-root>"),
            }
    snapshot = {
        "baseline_sha": "02f4bab9bc7562668ffc41d622c4274449933768",
        "recorded_unit_parameters": {"mcp_dev": params_dev, "mcp_prod": params_prod},
        "rendered_linux_units": rendered,
        "setup_write_preview": previews,
        "rpc_version": PROTOCOL_VERSION,
        "required_job_meta_fields": META_REQUIRED,
        "fixture_meta": {},
        "fixture_log_sha256": {},
        "linux_import_block_probe": [
            blocked(n)
            for n in (
                "binnacle.config",
                "binnacle.observability.logstats",
                "binnacle.features.commands.jobs",
                "binnacle.server",
            )
        ],
    }
    for p in sorted(
        (ROOT / "tests/contracts/fixtures/job_spool").glob("*/*/meta.json")
    ):
        key = str(p.relative_to(ROOT))
        snapshot["fixture_meta"][key] = json.loads(p.read_text())
    for p in sorted((ROOT / "tests/contracts/fixtures/job_spool").glob("*/*/out.log")):
        snapshot["fixture_log_sha256"][str(p.relative_to(ROOT))] = hashlib.sha256(
            p.read_bytes()
        ).hexdigest()
    path = HERE / "os0-host-baseline.json"
    path.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "unit_hashes": {
                    k: hashlib.sha256(v.encode()).hexdigest()
                    for k, v in rendered.items()
                },
                "provision_previews": {k: v["action"] for k, v in previews.items()},
                "import_block_results": {
                    item["module"]: item["exit"]
                    for item in snapshot["linux_import_block_probe"]
                },
                "fixture_records": len(snapshot["fixture_meta"]),
                "rpc_version": snapshot["rpc_version"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
