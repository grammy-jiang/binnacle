"""Build, inspect, install, and smoke the publishable distributions."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path


def _run(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def _build_project(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    repo = Path(__file__).resolve().parents[2]
    project = tmp_path / "project"
    project.mkdir()
    for name in (
        "pyproject.toml",
        "uv.lock",
        "build-constraints.txt",
        "README.md",
        "LICENSE",
    ):
        shutil.copy2(repo / name, project / name)
    shutil.copytree(
        repo / "src",
        project / "src",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info"),
    )

    in_project = False
    version: str | None = None
    for line in (project / "pyproject.toml").read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped == "[project]":
            in_project = True
            continue
        if in_project and stripped.startswith("["):
            break
        if in_project and stripped.startswith("version = "):
            version = stripped.partition("=")[2].strip().strip(chr(34))
            break
    assert version is not None, "project.version is required for distribution metadata"
    dist = project / "dist"

    uv = shutil.which("uv")
    assert uv is not None, "uv is required by the repository's build workflow"
    common = [
        uv,
        "build",
        "--no-sources",
        "--out-dir",
        str(dist),
        "--build-constraint",
        str(project / "build-constraints.txt"),
        "--require-hashes",
    ]

    sdist_build = _run([*common, "--sdist", "--clear"], cwd=project)
    assert sdist_build.returncode == 0, sdist_build.stderr
    sdists = list(dist.glob("*.tar.gz"))
    assert len(sdists) == 1

    # Build the wheel from the source distribution, not from the original tree.
    # This proves the sdist carries enough publishable source to reproduce it.
    wheel_build = _run([*common, "--wheel", str(sdists[0])], cwd=project)
    assert wheel_build.returncode == 0, wheel_build.stderr
    wheels = list(dist.glob("*.whl"))
    assert len(wheels) == 1
    return project, sdists[0], wheels[0], version


def _assert_sdist(sdist: Path, version: str) -> None:
    with tarfile.open(sdist, "r:gz") as archive:
        names = {member.name for member in archive.getmembers()}

    roots = {name.split("/", 1)[0] for name in names if "/" in name}
    assert len(roots) == 1
    root = roots.pop()
    assert version in root
    assert f"{root}/pyproject.toml" in names
    assert f"{root}/README.md" in names
    assert f"{root}/LICENSE" in names
    assert f"{root}/src/binnacle/server.py" in names
    assert f"{root}/src/binnacle/cli.py" in names
    assert f"{root}/src/binnacle/provenance.py" in names
    assert f"{root}/src/binnacle/py.typed" in names
    assert not any("/tests/" in name for name in names)


def _assert_wheel(wheel: Path, version: str) -> None:
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        assert "binnacle/server.py" in names
        assert "binnacle/cli.py" in names
        assert "binnacle/provenance.py" in names
        assert "binnacle/py.typed" in names
        # G6 Files tools are package-owned MCP adapters, not root-level aliases.
        assert "binnacle/features/files/files_server.py" in names
        for tool in ("read_file", "list_files", "edit_file", "write_file"):
            assert f"binnacle/features/files/tools/{tool}.py" in names
        assert "binnacle/tools/read_file.py" not in names
        # G7 removal must not leave any packaged root-level legacy MCP adapters.
        assert not any(name.startswith("binnacle/tools/") for name in names)
        for tool in ("run_command", "job_status", "stop_job"):
            assert f"binnacle/features/commands/tools/{tool}.py" in names
        assert "binnacle/companions/watchdog/ops/policy.py" in names
        assert not any(name.startswith("tests/") for name in names)

        entry_points = next(
            name for name in names if name.endswith(".dist-info/entry_points.txt")
        )
        entries = archive.read(entry_points).decode()
        expected = {
            "binnacle = binnacle.cli:main",
            "binnacle-jobs = binnacle.features.commands.job_manager:main",
            "binnacle-watchdog = binnacle.companions.watchdog.watchdog_cli:main",
            "binnacle-tunnel = binnacle.companions.tunnel.tunnel_cli:main",
        }
        assert all(entry in entries for entry in expected)

        metadata = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata_text = archive.read(metadata).decode()
        assert "Name: binnacle-mcp\n" in metadata_text
        assert f"Version: {version}\n" in metadata_text
        assert "License-Expression: MIT\n" in metadata_text
        assert "License-File: LICENSE\n" in metadata_text
        assert "Description-Content-Type: text/markdown\n" in metadata_text
        assert (
            "Project-URL: Repository, https://github.com/grammy-jiang/binnacle\n"
            in metadata_text
        )
        assert "Binnacle is a small MCP server" in metadata_text
        assert "Requires-Dist: fastmcp==4.1.0\n" in metadata_text
        assert any(name.endswith("/licenses/LICENSE") for name in names)


def _install_and_smoke(
    project: Path,
    wheel: Path,
    version: str,
    tmp_path: Path,
) -> None:
    uv = shutil.which("uv")
    assert uv is not None
    runtime_requirements = tmp_path / "runtime-requirements.txt"
    exported = _run(
        [
            uv,
            "export",
            "--locked",
            "--no-dev",
            "--no-emit-project",
            "--no-sources",
            "--output-file",
            str(runtime_requirements),
        ],
        cwd=project,
    )
    assert exported.returncode == 0, exported.stderr

    venv = tmp_path / "clean-venv"
    created = _run(
        [uv, "venv", "--python", sys.executable, str(venv)],
        cwd=project,
    )
    assert created.returncode == 0, created.stderr
    python = venv / "bin" / "python"

    installed_runtime = _run(
        [
            uv,
            "pip",
            "install",
            "--require-hashes",
            "--python",
            str(python),
            "-r",
            str(runtime_requirements),
        ],
        cwd=project,
    )
    assert installed_runtime.returncode == 0, installed_runtime.stderr

    installed_wheel = _run(
        [
            uv,
            "pip",
            "install",
            "--offline",
            "--python",
            str(python),
            "--no-deps",
            str(wheel),
        ],
        cwd=project,
    )
    assert installed_wheel.returncode == 0, installed_wheel.stderr

    import_env = os.environ.copy()
    import_env.pop("PYTHONPATH", None)
    import_env.pop("VIRTUAL_ENV", None)
    imported = _run(
        [
            str(python),
            "-c",
            (
                "from importlib.metadata import version; "
                "import binnacle, binnacle.features.commands.job_manager; "
                "print(version('binnacle-mcp')); "
                "print(binnacle.__file__)"
            ),
        ],
        cwd=tmp_path,
        env=import_env,
    )
    assert imported.returncode == 0, imported.stderr
    version_line, package_file = imported.stdout.strip().splitlines()
    assert version_line == version
    assert str(venv.resolve()) in str(Path(package_file).resolve())

    isolated_home = tmp_path / "home"
    isolated_home.mkdir()
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(isolated_home),
            "XDG_CONFIG_HOME": str(isolated_home / ".config"),
            "XDG_STATE_HOME": str(isolated_home / ".local" / "state"),
            "XDG_CACHE_HOME": str(isolated_home / ".cache"),
        }
    )
    env.pop("VIRTUAL_ENV", None)
    env.pop("PYTHONPATH", None)

    # The jobs entry point intentionally starts a service and therefore must not
    # be executed as a packaging smoke. Importing its module above validates it.
    for command in ("binnacle", "binnacle-watchdog", "binnacle-tunnel"):
        script = venv / "bin" / command
        assert script.is_file()
        result = _run(
            [str(script), "--help"],
            cwd=tmp_path,
            env=env,
        )
        assert result.returncode == 0, result.stderr

    assert (venv / "bin" / "binnacle-jobs").is_file()


def test_distributions_are_publishable_installable_and_smokeable(
    tmp_path: Path,
) -> None:
    project, sdist, wheel, version = _build_project(tmp_path)
    _assert_sdist(sdist, version)
    _assert_wheel(wheel, version)
    _install_and_smoke(project, wheel, version, tmp_path)
