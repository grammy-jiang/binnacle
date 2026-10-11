"""Unprivileged arm64 wheel/sdist build, locked install and import smoke.

Everything happens in a private temp dir; nothing is installed globally.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

TOOLS = [
    "read_file",
    "list_files",
    "search_text",
    "edit_file",
    "write_file",
    "run_command",
    "job_status",
    "stop_job",
]
DARWIN_MODULES = [
    "binnacle.deployment.darwin",
    "binnacle.deployment.darwin.plist",
    "binnacle.deployment.darwin.provisioner",
    "binnacle.deployment.darwin.setup",
]
PROBE = """
import importlib, json, sys
for m in {mods!r}:
    importlib.import_module(m)
from binnacle.mcp import tool_order
linux = sorted(m for m in sys.modules if m.startswith("binnacle.platform.linux"))
sysd = sorted(m for m in sys.modules if "systemd" in m)
print(json.dumps({{"tools": list(tool_order._RANK), "linux_loaded": linux, "systemd_loaded": sysd}}))
"""


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _run(cmd: list[str], cwd: Path) -> str:
    return subprocess.run(
        cmd, cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", type=Path, default=Path.cwd())
    ap.add_argument("--receipt", type=Path, required=True)
    ns = ap.parse_args()
    repo: Path = ns.repo.resolve()
    doc: dict[str, object] = {
        "machine": platform.machine(),
        "system": platform.system(),
        "full_parity": False,
    }
    with tempfile.TemporaryDirectory(prefix="r3pkg") as tmp:
        t = Path(tmp)
        dist = t / "dist"
        _run(["uv", "build", "--out-dir", str(dist)], repo)
        wheel = next(dist.glob("*.whl"))
        sdist = next(dist.glob("*.tar.gz"))
        doc["wheel"] = {"name": wheel.name, "sha256": _sha(wheel)}
        doc["sdist"] = {"name": sdist.name, "sha256": _sha(sdist)}
        with zipfile.ZipFile(wheel) as z:
            names = z.namelist()
        doc["wheel_has_darwin_modules"] = all(
            f"{m.replace('.', '/')}.py" in names
            or f"{m.replace('.', '/')}/__init__.py" in names
            for m in DARWIN_MODULES
        )
        doc["wheel_platform_tag_pure"] = wheel.name.endswith("-none-any.whl")
        venv = t / "venv"
        _run(["uv", "venv", "--python", sys.executable, str(venv)], repo)
        py = venv / "bin" / "python"
        req = t / "req.txt"
        req.write_text(
            _run(
                [
                    "uv",
                    "export",
                    "--locked",
                    "--no-dev",
                    "--no-emit-project",
                    "--format",
                    "requirements-txt",
                ],
                repo,
            )
        )
        _run(
            [
                "uv",
                "pip",
                "install",
                "--python",
                str(py),
                "--require-hashes",
                "-r",
                str(req),
            ],
            repo,
        )
        _run(
            ["uv", "pip", "install", "--python", str(py), "--no-deps", str(wheel)], repo
        )
        probe = json.loads(
            _run([str(py), "-I", "-c", PROBE.format(mods=DARWIN_MODULES)], t)
        )
        doc["tools"] = probe["tools"]
        doc["tools_stable"] = probe["tools"] == TOOLS
        doc["linux_only_modules_loaded_at_import"] = probe["linux_loaded"]
        doc["systemd_modules_loaded_at_import"] = probe["systemd_loaded"]
        ep = _run(
            [
                str(py),
                "-I",
                "-c",
                "import importlib.metadata as m;print(sorted(e.name for e in m.entry_points(group='console_scripts') if e.value.startswith('binnacle')))",
            ],
            t,
        )
        doc["console_scripts"] = ep.strip()
    doc["ok"] = bool(
        doc["machine"] == "arm64"
        and doc["tools_stable"]
        and doc["wheel_has_darwin_modules"]
        and not doc["linux_only_modules_loaded_at_import"]
        and not doc["systemd_modules_loaded_at_import"]
    )
    ns.receipt.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    print(json.dumps(doc, indent=1, sort_keys=True))
    return 0 if doc["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
