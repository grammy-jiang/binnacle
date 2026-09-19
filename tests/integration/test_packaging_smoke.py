"""Installed-package, console-entry-point, and portability smoke tests."""

import importlib.metadata
import importlib.resources
import os
import subprocess
import sys


def clean_env(config_file) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("BINNACLE_")}
    env["BINNACLE_CONFIG_FILE"] = str(config_file)
    return env


def test_distribution_exposes_both_console_entry_points():
    dist = importlib.metadata.distribution("binnacle-mcp")
    scripts = {
        ep.name: ep.value for ep in dist.entry_points if ep.group == "console_scripts"
    }

    assert scripts["binnacle"] == "binnacle.cli:main"
    assert scripts["binnacle-watchdog"] == "binnacle.watchdog_cli:main"


def test_py_typed_marker_is_installed():
    marker = importlib.resources.files("binnacle").joinpath("py.typed")
    assert marker.is_file()


def test_main_cli_help_is_executable_without_host_mutation(tmp_path):
    config_file = tmp_path / "missing.toml"
    proc = subprocess.run(
        [sys.executable, "-m", "binnacle.cli", "--help"],
        capture_output=True,
        text=True,
        check=False,
        env=clean_env(config_file),
        timeout=20,
    )

    assert proc.returncode == 0, proc.stderr
    for command in ("serve", "setup", "mode", "doctor", "stats", "token"):
        assert command in proc.stdout


def test_watchdog_cli_help_is_executable_without_host_mutation(tmp_path):
    config_file = tmp_path / "missing.toml"
    proc = subprocess.run(
        [sys.executable, "-m", "binnacle.watchdog_cli", "--help"],
        capture_output=True,
        text=True,
        check=False,
        env=clean_env(config_file),
        timeout=20,
    )

    assert proc.returncode == 0, proc.stderr
    for command in (
        "setup",
        "doctor",
        "run",
        "usb-reset",
        "pause",
        "resume",
        "history",
        "reload-driver",
        "status",
    ):
        assert command in proc.stdout


def test_core_server_imports_when_watchdog_companion_is_blocked(tmp_path):
    token = tmp_path / "token"
    token.write_text("Bearer integration-token\n")
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        f"""
[auth]
token_file = "{token}"

[indexed_context]
enabled = false
"""
    )
    script = r"""
import importlib.abc
import sys

class BlockWatchdog(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        blocked = (
            fullname == "binnacle.watchdog"
            or fullname.startswith("binnacle.watchdog_")
            or fullname == "binnacle.watchlog"
            or fullname.startswith("binnacle.ops.watchdog")
        )
        if blocked:
            raise ModuleNotFoundError(f"blocked companion import: {fullname}")
        return None

sys.meta_path.insert(0, BlockWatchdog())

import binnacle.config
import binnacle.cli
import binnacle.doctor
import binnacle.jobs
import binnacle.indexed_context
import binnacle.server

print("core-import-ok")
"""
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
        env=clean_env(config_file),
        timeout=30,
    )

    assert proc.returncode == 0, proc.stderr
    assert "core-import-ok" in proc.stdout


def test_server_import_fails_cleanly_when_configured_token_is_missing(tmp_path):
    missing = tmp_path / "missing-token"
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        f"""
[auth]
token_file = "{missing}"
"""
    )

    proc = subprocess.run(
        [sys.executable, "-c", "import binnacle.server"],
        capture_output=True,
        text=True,
        check=False,
        env=clean_env(config_file),
        timeout=30,
    )

    assert proc.returncode != 0
    assert str(missing) in proc.stderr
    assert "FileNotFoundError" in proc.stderr
